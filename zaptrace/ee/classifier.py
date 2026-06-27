"""Netlist classifier — auto-classifies nets by name and connected pin types.

Every net in a design is assigned a :class:`NetClass` that determines its
routing rules (trace width, clearance, via count, priority). Classification
is based on:

1. **Net name patterns** — well-known prefixes and suffixes (USB*, I2C*, VCC, GND…)
2. **Connected pin types** — power pins → power net, analog pins → analog net, etc.
3. **Component types** — USB connector on a net → differential, antenna → RF

The classifier is deterministic and idempotent. Call :func:`classify_design`
after parsing a design or synthesis output.
"""

from __future__ import annotations

import re

from zaptrace.core.models import Component, Design, NetClass

# ---------------------------------------------------------------------------
# Name-based pattern scoring
# ---------------------------------------------------------------------------

# Patterns are evaluated as regular expressions. The first match wins, so
# more specific patterns must appear before general ones.

_NAME_RULES: list[tuple[str, NetClass, str]] = [
    # Ground — must be checked before power (AGND is ground, not analog power)
    (r"^(GND|AGND|DGND|PGND|VSS|VSSA|VS S|GND_?[A-Z0-9]|SUB_GND)$", NetClass.GROUND, "ground_pattern"),
    (r"^(GND|AGND|DGND|PGND|VSS|VSSA|VSS_?)", NetClass.GROUND, "ground_prefix"),
    # RF
    (r"^(ANT|RF_|RFIO|BT_ANT|WIFI_ANT)", NetClass.RF, "rf_pattern"),
    (r"_ANT(_P|_N|_OUT)?$", NetClass.RF, "rf_suffix"),
    # Differential pairs
    (r"^(USB|HSD|DP|DM)", NetClass.DIFFERENTIAL, "differential_prefix"),
    (r"(_DP$|_DM$|_P$|_N$)", NetClass.DIFFERENTIAL, "differential_suffix"),
    (r"^SDIO_(CLK|CMD|D[0-3])", NetClass.SIGNAL_HIGH, "sdio_high_speed"),
    (r"^ETH_|^RMII_", NetClass.SIGNAL_HIGH, "ethernet"),
    # High-speed digital (>10 MHz)
    (r"^(CLK|MCLK|SCLK)", NetClass.SIGNAL_HIGH, "clock_prefix"),
    (r"_CLK$|_CLK\d$", NetClass.SIGNAL_HIGH, "clock_suffix"),
    (r"^HS_", NetClass.SIGNAL_HIGH, "high_speed_prefix"),
    # Reference voltages (classified as low-current power, not analog)
    (r"^(VREF|VREFP|VREFN)", NetClass.POWER_LOW, "reference_voltage"),
    # Analog
    (r"^(ADC|AIN)", NetClass.SIGNAL_ANALOG, "analog_prefix"),
    (r"(_ADC$|_ADC_|_AIN$)", NetClass.SIGNAL_ANALOG, "analog_suffix"),
    (r"^(SENSE|SENSEP|SENSEN)", NetClass.SIGNAL_ANALOG, "sense_prefix"),
    # I2C
    (r"^(I2C_|I3C_)", NetClass.SIGNAL_LOW, "i2c_prefix"),
    (r"^(SDA|SCL)$", NetClass.SIGNAL_LOW, "i2c_pins"),
    # SPI
    (r"^(SPI_|QSPI_)", NetClass.SIGNAL_LOW, "spi_prefix"),
    (r"^(MOSI|MISO|SCK|NSS|CS[0-9]?)$", NetClass.SIGNAL_LOW, "spi_pins"),
    # UART
    (r"^(UART_|RS232_|RS485_)", NetClass.SIGNAL_LOW, "uart_prefix"),
    (r"^(TX|RX|RTS|CTS|TXD|RXD)$", NetClass.SIGNAL_LOW, "uart_pins"),
    (r"_TX$|_RX$", NetClass.SIGNAL_LOW, "uart_suffix"),
    # Power rails — voltage-prefixed vs named
    (r"^(VCC|VDD|VDDIO|VBAT|VUSB|VIN|VOUT|VDD_|VCC_)", NetClass.POWER_MED, "power_rail"),
    (r"^(3V3|3\.3V|1V8|1\.8V|2V5|2\.5V|5V|12V)", NetClass.POWER_MED, "voltage_power"),
    (r"^(VREF|VREFP|VREFN)", NetClass.POWER_LOW, "reference_voltage"),
    (r"_VDD$|_VCC$|_VIN$", NetClass.POWER_MED, "power_suffix"),
    # Default: signal
]

# Voltage thresholds for power classification (from net name heuristics)
_VOLTAGE_POWER_MAP: dict[float, NetClass] = {
    0.9: NetClass.POWER_LOW,
    1.2: NetClass.POWER_LOW,
    1.8: NetClass.POWER_LOW,
    2.5: NetClass.POWER_LOW,
    3.3: NetClass.POWER_MED,
    5.0: NetClass.POWER_MED,
    12.0: NetClass.POWER_HIGH,
    24.0: NetClass.POWER_HIGH,
    48.0: NetClass.POWER_HIGH,
}


def _classify_by_name(net_name: str) -> NetClass | None:
    """Classify a net solely by its name against known patterns.

    Returns ``None`` if no pattern matches (fall back to pin-type analysis).
    """
    for pattern, net_class, _tag in _NAME_RULES:
        if re.search(pattern, net_name, re.IGNORECASE):
            return net_class
    return None


# ---------------------------------------------------------------------------
# Pin-type-based classification
# ---------------------------------------------------------------------------


def _classify_by_pin_types(design: Design, net_id: str, net_name: str) -> NetClass:
    """Refine net classification by examining connected pin types.

    This is used as a fallback when name-based classification is ambiguous
    or as a confidence boost for name-based results.
    """
    net = design.nets.get(net_id)
    if not net or not net.nodes:
        # No connected pins — keep default SIGNAL_LOW
        return NetClass.SIGNAL_LOW

    pin_types: set[str] = set()
    component_types: set[str] = set()

    for node in net.nodes:
        comp = _find_component_by_ref(design, node.component_ref)
        if comp is None:
            continue
        component_types.add(comp.type.lower())
        pin = comp.pins.get(node.pin_name)
        if pin is not None:
            pin_types.add(pin.type.value if hasattr(pin.type, "value") else str(pin.type).lower())

    # Strong signals from pin types
    if "ground" in pin_types or "power" in pin_types and net_name.upper().startswith(("GND", "VSS")):
        return NetClass.GROUND

    # Component-type-based heuristics
    for ct in component_types:
        if "antenna" in ct or "rf" in ct:
            return NetClass.RF
        if "usb" in ct or "hdmi" in ct or "ethernet" in ct:
            return NetClass.DIFFERENTIAL
        if "adc" in ct or "analog" in ct:
            return NetClass.SIGNAL_ANALOG

    # Power pins on the net → classify as power
    has_power_pin = "power" in pin_types
    has_output_pin = "output" in pin_types
    if has_power_pin and has_output_pin:
        return NetClass.POWER_MED
    if has_power_pin:
        return NetClass.POWER_LOW

    return NetClass.SIGNAL_LOW


def _find_component_by_ref(design: Design, ref: str) -> Component | None:
    """Find a component by its reference designator (e.g., 'R1', 'C2')."""
    return design.get_component(ref)


# ---------------------------------------------------------------------------
# Voltage heuristic from net name
# ---------------------------------------------------------------------------

_VOLTAGE_PATTERN = re.compile(r"(\d+[Vv])|(\d+[Pp]\d+[Vv])")
_VOLTAGE_NUM_PATTERN = re.compile(r"\b(\d+[.]?\d*)\b")


def _extract_voltage(net_name: str) -> float | None:
    """Try to extract a voltage value from a power net name.

    Handles patterns like ``3V3``, ``1V8``, ``5V``, ``3.3V``, ``12V``.
    Returns ``None`` when no voltage pattern is detected.
    """
    m = _VOLTAGE_PATTERN.search(net_name)
    if m:
        raw = m.group(0)
        # Remove 'V' or 'v', replace 'P' with '.'
        cleaned = raw[:-1].replace("P", ".").replace("p", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _classify_power_by_voltage(net_name: str) -> NetClass | None:
    """Classify a power net by its voltage heuristics."""
    voltage = _extract_voltage(net_name)
    if voltage is not None:
        for thresh, nc in sorted(_VOLTAGE_POWER_MAP.items()):
            if voltage <= thresh + 0.05:  # small tolerance
                return nc
        return NetClass.POWER_HIGH  # > 48V
    return None


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------


def classify_design(design: Design) -> Design:
    """Auto-classify every net in a design and return the updated design.

    Classification pipeline per net:

    1. **Name match** — check against ``_NAME_RULES`` patterns
    2. **Voltage heuristic** — if classified as power, refine LOW/MED/HIGH
    3. **Pin-type fallback** — if name is ambiguous, use connected pin types
    4. **Store** — populate ``design.net_classes[net_id]``

    The design is returned with ``net_classes`` populated. If a net was
    already manually classified (present in ``design.net_classes``), it is
    preserved unless ``force`` is ``True``.

    Args:
        design: The design to classify.

    Returns:
        The same design instance with ``net_classes`` populated.
    """
    if design.net_classes is None:
        design.net_classes = {}

    for net_id, net in design.nets.items():
        # Preserve existing manual classification
        if net_id in design.net_classes:
            continue

        net_name = net.name.strip()

        # Step 1: Name-based classification
        name_class = _classify_by_name(net_name)

        # Step 2: If power, refine by voltage
        if name_class in (NetClass.POWER_LOW, NetClass.POWER_MED, NetClass.POWER_HIGH, None):
            voltage_class = _classify_power_by_voltage(net_name)
            if voltage_class is not None:
                name_class = voltage_class

        # Step 3: Pin-type fallback for unclassified nets
        if name_class is None:
            name_class = _classify_by_pin_types(design, net_id, net_name)

        design.net_classes[net_id] = name_class

    return design


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def get_net_class(design: Design, net_id: str) -> NetClass:
    """Get the classified net class for a specific net.

    If ``classify_design`` has not been called yet, runs classification first.
    """
    if design.net_classes is None or net_id not in design.net_classes:
        classify_design(design)
    # classify_design always sets design.net_classes
    assert design.net_classes is not None
    return design.net_classes.get(net_id, NetClass.SIGNAL_LOW)


def summarize_classification(design: Design) -> dict[str, list[str]]:
    """Summarize net classification for reporting and debugging.

    Returns a mapping from ``NetClass`` value to list of net names:

    .. code-block:: python

        {
            "ground": ["GND", "AGND"],
            "power_med": ["VCC", "3V3"],
            "signal_low": ["SDA", "SCL"],
        }
    """
    if design.net_classes is None:
        classify_design(design)

    summary: dict[str, list[str]] = {}
    for net_id, nc in (design.net_classes or {}).items():
        key = nc.value if hasattr(nc, "value") else str(nc)
        if key not in summary:
            summary[key] = []
        net = design.nets.get(net_id)
        summary[key].append(net.name if net else net_id)
    return summary
