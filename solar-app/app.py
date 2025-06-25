import pandas as pd
import pvlib
from flask import Flask, request, render_template, send_file, jsonify, send_from_directory
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO
import base64
import pytz
import numpy as np
from datetime import datetime, timedelta
from timezonefinder import TimezoneFinder
import os

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    global data
    data = None
    chart_url = None
    chart_filename = ""
    special_times = []
    special_angles = []
    lat = default_latitude
    lon = default_longitude
    altitude = default_altitude
    angle_threshold = 1.0
    xtick_minutes = 60
    ytick_degrees = 10

    timezone = tf.timezone_at(lng=lon, lat=lat) or default_tz
    tzinfo = pytz.timezone(timezone)
    now = datetime.now(tzinfo)
    default_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    default_end = default_start + timedelta(days=1)

    if request.method == 'POST':
        start = pd.to_datetime(request.form['start'])
        end = pd.to_datetime(request.form['end'])
        interval = int(request.form['interval'])
        special_times_raw_list = request.form.getlist('special_times')
        special_angles_raw_list = request.form.getlist('special_angles')

        lat = float(request.form.get('latitude', lat))
        lon = float(request.form.get('longitude', lon))
        altitude = float(request.form.get('altitude', altitude))
        angle_threshold = float(request.form.get('angle_threshold', angle_threshold))
        xtick_minutes = int(request.form.get('xtick_minutes', xtick_minutes))
        ytick_degrees = int(request.form.get('ytick_degrees', ytick_degrees))
        timezone = tf.timezone_at(lng=lon, lat=lat) or default_tz
        tzinfo = pytz.timezone(timezone)
        data = getSolarElevationAngleData(start, end, interval, lat, lon, altitude, timezone)

        special_times = [
            tzinfo.localize(pd.to_datetime(t.strip()))
            for t in special_times_raw_list
            if t.strip()
        ]

        special_angles = [
            float(a.strip())
            for a in special_angles_raw_list
            if a.strip()
        ]

        highlight_indices = set()
        highlight_times = set()

        for target in special_times:
            closest_idx = (data['Time'] - target).abs().idxmin()
            highlight_indices.add(closest_idx)
            highlight_times.add(data.at[closest_idx, 'Time'])

        for angle in special_angles:
            matching = data[(data['Solar Elevation Angle'] - angle).abs() <= angle_threshold]
            highlight_indices.update(matching.index)
            highlight_times.update(matching['Time'].tolist())

        data['highlight'] = data.index.isin(highlight_indices)

        fig, ax = plt.subplots(figsize=(10, 8))
        ax.plot(data['Time'], data['Solar Elevation Angle'], label='Solar Elevation Angle')
        for t in sorted(highlight_times):
            ax.axvline(t, color='red', linestyle='--')

        xticks = pd.date_range(start=start, end=end, freq=f'{xtick_minutes}min', tz=timezone)
        ax.set_xticks(xticks)
        def format_xtick(x, pos=None):
            dt = mdates.num2date(x, tz=timezone)
            if dt.hour == 0 and dt.minute == 0:
                return dt.strftime('%m-%d %H:%M')
            else:
                return dt.strftime('%H:%M')
        ax.xaxis.set_major_formatter(plt.FuncFormatter(format_xtick))
        ax.tick_params(axis='x', labelrotation=90)

        y_min = np.floor(data['Solar Elevation Angle'].min() / ytick_degrees) * ytick_degrees
        y_max = np.ceil(data['Solar Elevation Angle'].max() / ytick_degrees) * ytick_degrees
        yticks = np.arange(y_min, y_max + ytick_degrees, ytick_degrees)
        ax.set_yticks(yticks)

        ax.grid(True)
        ax.set_xlabel('Time')
        ax.set_ylabel('Solar Elevation Angle (deg)')
        ax.set_title(f'Solar Elevation Angle: {start.strftime("%Y-%m-%d %H:%M")} to {end.strftime("%Y-%m-%d %H:%M")}')
        ax.legend()
        plt.tight_layout()

        img = BytesIO()
        fig.savefig(img, format='png')
        img.seek(0)
        chart_url = base64.b64encode(img.getvalue()).decode()
        plt.close()

        chart_filename = f"{start.strftime('%Y-%m-%d_%H%M')}_{end.strftime('%Y-%m-%d_%H%M')}_{interval}min_{lat}_{lon}_{altitude}_chart.png"

        return render_template(
            'index.html', data=data, chart_url=chart_url, chart_filename=chart_filename,
            special_times=special_times, special_angles=special_angles,
            angle_threshold=angle_threshold,
            xtick_minutes=xtick_minutes, ytick_degrees=ytick_degrees,
            default_start=start.strftime('%Y-%m-%d %H:%M'),
            default_end=end.strftime('%Y-%m-%d %H:%M'),
            timezone=timezone
        )

    return render_template(
        'index.html', data=data, chart_url=chart_url, chart_filename=chart_filename,
        special_times=special_times, special_angles=special_angles,
        angle_threshold=angle_threshold,
        xtick_minutes=xtick_minutes, ytick_degrees=ytick_degrees,
        default_start=default_start.strftime('%Y-%m-%d %H:%M'),
        default_end=default_end.strftime('%Y-%m-%d %H:%M'),
        timezone=timezone
    )

@app.route('/export', methods=['POST'])
def export_csv():
    global data
    start = pd.to_datetime(request.form['start'])
    end = pd.to_datetime(request.form['end'])
    interval = int(request.form['interval'])
    lat = float(request.form.get('latitude', default_latitude))
    lon = float(request.form.get('longitude', default_longitude))
    altitude = float(request.form.get('altitude', default_altitude))
    df = data

    filename = f"{start.strftime('%Y-%m-%d_%H%M')}_{end.strftime('%Y-%m-%d_%H%M')}_{interval}min_{lat}_{lon}_{altitude}_table.csv"

    buffer = BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='text/csv'
    )

@app.route("/get_timezone")
def get_timezone():
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    tz = tf.timezone_at(lat=lat, lng=lon)
    return jsonify({"timezone": tz})

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

def calculate_solar_solar_elevation(local_dt, latitude, longitude, altitude, timezone):
    local_dt_str = local_dt.strftime('%Y-%m-%d %H:%M:%S')
    time = pd.Timestamp(local_dt_str, tz=timezone)
    location = pvlib.location.Location(latitude, longitude, timezone, altitude)
    solar_position = location.get_solarposition(time, method='nrel_numpy')
    solar_elevation = solar_position['elevation'].values[0]
    return solar_elevation

def getSolarElevationAngleData(start, end, interval, latitude, longitude, altitude, timezone):
    datetimes = pd.date_range(start=start, end=end, freq=f'{interval}min', tz=timezone)
    solar_elevations = []
    for dt in datetimes:
        local_time = dt
        solar_elevation = calculate_solar_solar_elevation(local_time, latitude, longitude, altitude, timezone)
        solar_elevations.append(solar_elevation)
    data = pd.DataFrame({
        'Time': datetimes,
        'Solar Elevation Angle': solar_elevations
    })
    return data

tf = TimezoneFinder()
all_timezones = pytz.all_timezones
default_tz = "Asia/Tokyo"
default_latitude = 35.613288497743945
default_longitude = 139.54987863680572
default_altitude = 58.6
data = None
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

