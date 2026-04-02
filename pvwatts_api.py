import requests

PVWATTS_URL = "https://developer.nrel.gov/api/pvwatts/v8.json"

API_KEY = "123abc" #  obrain from https://developer.nlr.gov/signup/

KW_PER_M2 = 0.20 # 400W panel (77″ × 39″) at 10deg tilt

DERATING_FACTOR = 0.85

FIXED_PARAMS = {
    'format': 'json',
    'api_key': API_KEY,
    'system_capacity': 1,  # kW
    'tilt': 10,  # degrees
    'module_type': 0,  # 0 for standard, 1 for premium
    'losses': 14,  # %
    'array_type': 1,  # 1 for fixed roof mount
    'azimuth': 180,  # degrees
    'dataset': 'nsrdb', # climate dataset
    'timeframe': 'monthly',  # 'hourly' or 'monthly'
    'dc_ac_ratio': 1.2, # DC/AC ratio
}

def get_pv_annual_kWh_per_kW(lat, lon) -> float:

    params = {
        **FIXED_PARAMS,
        'lat': lat,
        'lon': lon
    }

    response = requests.get(PVWATTS_URL, params=params)

    if response.status_code == 200:
        data = response.json()
        kWh_per_kW = data['outputs']['ac_annual'] * DERATING_FACTOR
    else:
        print(response.text)
        raise Exception(f"Request failed with status code {response.status_code}")
    
    return kWh_per_kW