from e400plus.protocol import Metrics, ShowMask, build_stats_payload, build_shutdown_payload, describe_payload


def test_stats_header_and_temp():
    m = Metrics(
        cpu_temp_c=42.5,
        cpu_usage=55,
        cpu_power_w=135.7,
        cpu_freq_mhz=3819,
        cpu_voltage=1.21,
        gpu_temp_c=39.0,
        gpu_usage=10,
        show=ShowMask.CPU_TEMP | ShowMask.CPU_USAGE,
        celsius=True,
    )
    payload = build_stats_payload(m)
    assert len(payload) == 64
    assert payload[0:3] == bytes([0, 1, 2])
    assert payload[3] == 42
    assert payload[4] == 50
    assert payload[5] == 0  # celsius
    assert payload[6] == 55
    # power 135.7 → lo2=35, frac=70, hundreds=1
    assert payload[3 + 4] == 35
    assert payload[3 + 5] == 70
    assert payload[3 + 0x1F] == 1
    # freq 3819 → 38, 19
    assert payload[3 + 6] == 38
    assert payload[3 + 7] == 19
    assert payload[3 + 0x24] == int(ShowMask.CPU_TEMP | ShowMask.CPU_USAGE)
    assert "stats" in describe_payload(payload)


def test_shutdown_frame():
    payload = build_shutdown_payload()
    assert len(payload) == 64
    assert payload[1] == 0x0F
    assert describe_payload(payload).startswith("shutdown")


def test_fahrenheit_flag():
    m = Metrics(cpu_temp_c=0, celsius=False)
    payload = build_stats_payload(m)
    assert payload[5] == 1
