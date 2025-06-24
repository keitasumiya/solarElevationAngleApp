import pandas as pd
import pvlib
from flask import Flask, request, render_template, send_file
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO
import base64
import pytz
import numpy as np
from datetime import datetime, timedelta
import os

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    data = None
    chart_url = None
    chart_filename = ""
    special_times = []
    special_angles = []
    lat = 35.6895
    lon = 139.6917
    altitude = 0
    tz_offset = 9  # Default +9 for Asia/Tokyo
    angle_threshold = 1.0
    xtick_minutes = 60
    ytick_degrees = 10

    timezone = pytz.FixedOffset(tz_offset * 60)
    now = datetime.now(timezone)
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
        tz_offset = int(request.form.get('timezone', tz_offset))
        angle_threshold = float(request.form.get('angle_threshold', angle_threshold))
        xtick_minutes = int(request.form.get('xtick_minutes', xtick_minutes))
        ytick_degrees = int(request.form.get('ytick_degrees', ytick_degrees))
        timezone = pytz.FixedOffset(tz_offset * 60)

        times = pd.date_range(start=start, end=end, freq=f'{interval}min', tz=timezone)
        solpos = pvlib.solarposition.get_solarposition(times, lat, lon, altitude=altitude)
        data = pd.DataFrame({
            'Time': times,
            'Solar Altitude': solpos['apparent_elevation']
        })

        special_times = [
            timezone.localize(pd.to_datetime(t.strip()))
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
            matching = data[(data['Solar Altitude'] - angle).abs() <= angle_threshold]
            highlight_indices.update(matching.index)
            highlight_times.update(matching['Time'].tolist())

        data['highlight'] = data.index.isin(highlight_indices)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(data['Time'], data['Solar Altitude'], label='Solar Altitude')
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

        y_min = np.floor(data['Solar Altitude'].min() / ytick_degrees) * ytick_degrees
        y_max = np.ceil(data['Solar Altitude'].max() / ytick_degrees) * ytick_degrees
        yticks = np.arange(y_min, y_max + ytick_degrees, ytick_degrees)
        ax.set_yticks(yticks)

        ax.grid(True)
        ax.set_xlabel('Time')
        ax.set_ylabel('Solar Altitude (deg)')
        ax.set_title(f'Solar Altitude: {start.strftime("%Y-%m-%d %H:%M")} to {end.strftime("%Y-%m-%d %H:%M")}')
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
            default_end=end.strftime('%Y-%m-%d %H:%M')
        )

    return render_template(
        'index.html', data=data, chart_url=chart_url, chart_filename=chart_filename,
        special_times=special_times, special_angles=special_angles,
        angle_threshold=angle_threshold,
        xtick_minutes=xtick_minutes, ytick_degrees=ytick_degrees,
        default_start=default_start.strftime('%Y-%m-%d %H:%M'),
        default_end=default_end.strftime('%Y-%m-%d %H:%M')
    )

@app.route('/export', methods=['POST'])
def export_csv():
    start = pd.to_datetime(request.form['start'])
    end = pd.to_datetime(request.form['end'])
    interval = int(request.form['interval'])
    lat = float(request.form.get('latitude', 35.6895))
    lon = float(request.form.get('longitude', 139.6917))
    altitude = float(request.form.get('altitude', 0))
    tz_offset = int(request.form.get('timezone', 9))
    timezone = pytz.FixedOffset(tz_offset * 60)

    times = pd.date_range(start=start, end=end, freq=f'{interval}min', tz=timezone)
    solpos = pvlib.solarposition.get_solarposition(times, lat, lon, altitude=altitude)
    df = pd.DataFrame({
        'Time': times,
        'Solar Altitude': solpos['apparent_elevation']
    })

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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
