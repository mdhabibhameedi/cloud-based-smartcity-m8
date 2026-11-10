r"""Generate reproducible SYNTHETIC traffic and street-lighting datasets.
Run from the project: .\.venv\Scripts\python.exe src\prepare_datasets.py
Uses only the Python standard library. No AWS access or downloads.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 808
DAYS = 60
ZONES = {'Z01': ('Residential', 45, 60), 'Z02': ('Commercial', 85, 80),
         'Z03': ('Industrial', 65, 70), 'Z04': ('City_Centre', 110, 100)}
START = datetime(2026, 8, 1, tzinfo=timezone.utc)

def csv_text(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()

def build():
    rng = random.Random(SEED)
    traffic, energy = [], []
    for step in range(DAYS * 24):
        dt = START + timedelta(hours=step)
        stamp = dt.isoformat().replace('+00:00', 'Z')
        # Fictional city uses UTC as its simulation clock; these are not solar observations.
        night = int(dt.hour >= 18 or dt.hour < 6)
        weekend = dt.weekday() >= 5
        rush = math.exp(-((dt.hour-8)/1.8)**2) + 1.1*math.exp(-((dt.hour-17)/2.1)**2)
        rain = round(max(0, rng.gauss(2.0, 1.2)), 2) if rng.random() < .18 else 0.0
        for zone, (kind, base_flow, lamps) in ZONES.items():
            multiplier = (.78 if weekend else 1.0)
            variation = 1.0 + .08*math.sin(2*math.pi*step/(24*14))
            flow = max(0, round(base_flow * (.20 + .55*(not night) + rush) * multiplier * variation
                                * (1-.025*min(rain, 5)) + rng.gauss(0, base_flow*.15)))
            key = f'{zone}-{dt:%Y%m%dT%H%MZ}'
            traffic.append({'record_id': 'traffic-'+key, 'timestamp_utc': stamp,
                'zone_id': zone, 'zone_type': kind, 'vehicle_count': flow,
                'rainfall_mm': rain, 'interval_minutes': 60, 'is_synthetic': 'true'})
            # Baseline energy is independent of traffic: fixed full-power lighting at night.
            # Adaptive lighting is a later comparison, not built into this baseline dataset.
            energy_kwh = round(lamps * 70 / 1000 * night * rng.uniform(.98, 1.02), 4)
            energy.append({'record_id': 'energy-'+key, 'timestamp_utc': stamp,
                'zone_id': zone, 'zone_type': kind, 'lamp_count': lamps,
                'rated_power_w': 70, 'lighting_on': night,
                'energy_kwh': energy_kwh, 'interval_minutes': 60, 'is_synthetic': 'true'})
    return traffic, energy

def validate(traffic, energy):
    expected = DAYS * 24 * len(ZONES)
    checks = {}
    for name, rows in [('traffic', traffic), ('energy', energy)]:
        checks[name+'_row_count'] = len(rows) == expected
        checks[name+'_unique_ids'] = len({r['record_id'] for r in rows}) == expected
        checks[name+'_no_missing_values'] = all(v is not None and v != '' for r in rows for v in r.values())
        checks[name+'_synthetic_labels'] = all(r['is_synthetic'] == 'true' for r in rows)
        checks[name+'_hourly_continuity'] = all(
            [r['timestamp_utc'] for r in rows if r['zone_id']==z] ==
            [(START+timedelta(hours=h)).isoformat().replace('+00:00','Z') for h in range(DAYS*24)]
            for z in ZONES)
    checks['matching_zone_timestamp_pairs'] = (
        {(r['zone_id'],r['timestamp_utc']) for r in traffic} ==
        {(r['zone_id'],r['timestamp_utc']) for r in energy})
    checks['valid_traffic_values'] = all(isinstance(r['vehicle_count'], int) and r['vehicle_count'] >= 0 and r['rainfall_mm'] >= 0 for r in traffic)
    checks['valid_energy_values'] = all(r['energy_kwh'] >= 0 and (r['lighting_on']==1 or r['energy_kwh']==0) for r in energy)
    checks['all_checks_passed'] = all(checks.values())
    if not checks['all_checks_passed']:
        raise ValueError('Validation failed: '+str(checks))
    return {'status':'PASS', 'source':'SYNTHETIC - not real city measurements',
        'seed': SEED, 'days': DAYS, 'zones': len(ZONES), 'rows_per_dataset': expected,
        'start_utc': traffic[0]['timestamp_utc'], 'end_utc': traffic[-1]['timestamp_utc'],
        'checks':checks}

README = '''# Stage 4 - Synthetic dataset specification

## Source and scope
Both datasets are generated locally by src/prepare_datasets.py (seed 808).
They are fictional, reproducible demonstration inputs, not observations from Newvale
or another real city. No third-party dataset is downloaded. No personal data is used.
The assignment allows mocked data for implementation/simulation.

## Coverage and interpretation
60 days from 2026-08-01 00:00 UTC through 2026-09-29 23:00 UTC.
Four zones, hourly resolution: 5,760 records per dataset, 11,520 total.
Timestamps label the START of each one-hour observation interval.
Use (zone_id, timestamp_utc) to join; record_id includes the dataset prefix.
The fictional city uses UTC as its local simulation clock, not Stockholm local time.
Night is assumed to be 18:00-06:00 UTC for all dates; no astronomical calculation.
Stockholm is the AWS hosting region, not the claimed location of these observations.

## Traffic dictionary
- record_id: stable unique traffic record identifier.
- timestamp_utc: ISO 8601 UTC interval start.
- zone_id / zone_type: fictional zone identifier and descriptive category.
- vehicle_count: non-negative integer vehicles counted during the hour.
- rainfall_mm: simulated rainfall during that hour; shared across zones.
- interval_minutes: 60.
- is_synthetic: true on every row.

## Energy dictionary
- record_id: stable unique energy record identifier.
- timestamp_utc / zone_id / zone_type: same meanings as traffic.
- lamp_count: assumed installed lamps (60, 80, 70, 100 by zone).
- rated_power_w: assumed 70 W per lamp.
- lighting_on: 1 at assumed night hours, otherwise 0.
- energy_kwh: simulated aggregate zone lighting consumption for the hour.
  Formula: lamp_count * 70 / 1000 * lighting_on * random factor [0.98, 1.02].
- interval_minutes: 60; is_synthetic: true.

## Method and limits
Traffic combines morning/evening peaks, weekday effects, fortnightly variation,
rainfall effects and seeded random noise. It is not calibrated against real traffic.
Energy is a FIXED-lighting baseline, independent of traffic volume. A later adaptive
lighting simulation will document control thresholds and assumed dimming fractions.
Any apparent energy savings are scenario estimates, not measured real-world savings.
Future-hour traffic predictions must use information available at forecast time.
Split by timestamp across all zones: first 48 days for training (4,608 rows), final
12 days for held-out testing (1,152 rows). Tune within training only. Never randomly
split hourly rows or include same-target/future observations in model inputs.
Model metrics on synthetic data establish pipeline behaviour, not real-world accuracy.

## Validation and later preparation
results/dataset_validation.json records completeness, unique identifiers, continuity,
non-negative values, synthetic labels, matching keys, and SHA-256 file fingerprints.
The baseline datasets intentionally contain no missing or malformed records.
Create separate malformed/duplicate messages later for ingestion tests; preserve raw data.
Feature engineering and model-specific processed files belong in Stage 7.

## Replay note
Keep timestamp_utc as historical event time and add a separate sent_at_utc timestamp
when replaying into AWS. Measure pipeline latency using send/receipt timestamps,
not the historical observation date. Keep stable record IDs during retries.
The pair totals 11,520 messages if fully replayed, exceeding the INITIAL 10,000-message
cost scenario. Replay a bounded subset for initial cloud tests and update the estimate
before any full replay. Local model training can use all records without cloud ingestion.
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=Path(__file__).resolve().parents[1])
    root=parser.parse_args().output_root.resolve()
    traffic,energy=build()
    report=validate(traffic,energy)
    contents={'data/raw/traffic_synthetic.csv':csv_text(traffic),
              'data/raw/energy_synthetic.csv':csv_text(energy),
              'docs/Dataset-Specification.md':README}
    report['sha256']={name:hashlib.sha256(value.encode('utf-8')).hexdigest()
        for name,value in contents.items() if name.endswith('.csv')}
    contents['results/dataset_validation.json']=json.dumps(report,indent=2)+'\n'
    # Refuse to overwrite existing edited data. Identical reruns are safe.
    for rel,content in contents.items():
        target=root/rel
        if target.exists() and target.read_bytes()!=content.encode('utf-8'):
            raise SystemExit('Existing different file preserved: '+str(target))
    for rel,content in contents.items():
        target=root/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(content.encode('utf-8'))
    print('Traffic records: 5760')
    print('Energy records: 5760')
    print('Matched zone/timestamp pairs: 5760')
    print('Dataset validation: PASS')
    print('Source: SYNTHETIC (not real-world measurements)')
    print('Saved in: '+str(root))

if __name__=='__main__':
    main()
