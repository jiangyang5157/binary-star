Check whether the current time falls within DeepSeek API peak hours, and show
the distance to the nearest peak/off-peak transition.

Run:
```bash
python3 -c "
from datetime import datetime, timezone, timedelta

now = datetime.now(timezone.utc)
# Peak windows (UTC): 01:00-04:00 and 06:00-10:00
peaks = [
    (1, 4, '01:00–04:00 UTC (09:00–12:00 UTC+8)'),
    (6, 10, '06:00–10:00 UTC (14:00–18:00 UTC+8)'),
]

in_peak = False
current_peak = None
for start_h, end_h, label in peaks:
    if start_h <= now.hour + now.minute / 60 < end_h:
        in_peak = True
        current_peak = (start_h, end_h, label)
        break

now_str = now.strftime('%Y-%m-%d %H:%M:%S UTC')
local_str = (now + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S UTC+8')

print(f'Now: {now_str} / {local_str}')
print()

if in_peak:
    end_dt = now.replace(hour=current_peak[1], minute=0, second=0, microsecond=0)
    remaining = end_dt - now
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    print(f'🔴 IN PEAK — {current_peak[2]}')
    print(f'   Peak ends in: {hours}h {minutes}m')
    print(f'   Prices are 2x off-peak.')
else:
    # Find next peak
    next_peak = None
    min_dist = float('inf')
    for start_h, end_h, label in peaks:
        start_dt = now.replace(hour=start_h, minute=0, second=0, microsecond=0)
        if start_dt <= now:
            start_dt += timedelta(days=1)
        dist = (start_dt - now).total_seconds()
        if dist < min_dist:
            min_dist = dist
            next_peak = (start_dt, end_h, label)

    if next_peak:
        dist_dt = next_peak[0] - now
        hours = int(dist_dt.total_seconds() // 3600)
        minutes = int((dist_dt.total_seconds() % 3600) // 60)
        peak_end = next_peak[0].replace(hour=next_peak[1])
        duration = peak_end - next_peak[0]
        dur_h = int(duration.total_seconds() // 3600)
        print(f'🟢 OFF-PEAK — regular pricing')
        print(f'   Next peak: {next_peak[2]}')
        print(f'   Starts in: {hours}h {minutes}m')
        print(f'   Duration:  {dur_h}h')
"
```
