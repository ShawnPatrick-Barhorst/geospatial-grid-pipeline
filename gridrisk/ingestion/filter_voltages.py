#TODO: Reevaluate the need for these functions. Would be better to do filtering after voltage string -> list conversion.

def parse_min_voltage(voltage_str):
    """Extract the minimum voltage from a potentially multi-value string"""
    if not voltage_str:
        return None
    try:
        values = [int(v.strip()) for v in voltage_str.split(';') if v.strip().isdigit()]
        return max(values) if values else None  # use max — the highest voltage on the corridor
    except:
        return None
    

def filter_voltages(ways, transmission_threshold=69000):

    transmission_lines = []
    distribution_lines = []
    unknown_voltage    = []
    
    for line in ways:
        voltage_str = line.get('tags', {}).get('voltage')
        max_voltage = parse_min_voltage(voltage_str)
        
        if max_voltage is None:
            unknown_voltage.append(line)
        elif max_voltage >= transmission_threshold:
            transmission_lines.append(line)
        else:
            distribution_lines.append(line)

    return transmission_lines