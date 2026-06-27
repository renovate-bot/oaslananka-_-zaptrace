"""Net-naming policy for clean, readable schematics. (#105 scope)

Provides canonical net name generators for common signal types so that
synthesized schematics use consistent, EDA-tool-friendly names instead of
auto-generated tokens like ``Net-(U1-Pin-3)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_+\-\.]")
_LEADING_DIGIT_RE = re.compile(r"^[0-9]")


@dataclass(frozen=True)
class NetNamePolicy:
    """Canonical naming rules for a signal category."""

    category: str
    pattern: str
    examples: list[str]
    notes: str


POLICIES: list[NetNamePolicy] = [
    NetNamePolicy(
        category="power",
        pattern="{RAIL_NAME}  (e.g. VCC, VDD, +3V3, +5V, +12V, VBAT, VBUS)",
        examples=["VCC", "VDD", "+3V3", "+5V0", "+12V", "VBAT", "VBUS"],
        notes=(
            "Use all-caps. Prefix with '+' for positive DC rails. "
            "Do not use spaces or slashes. "
            "Derived rails: append voltage: '+3V3_MCU', '+1V8_IO'."
        ),
    ),
    NetNamePolicy(
        category="ground",
        pattern="GND | AGND | PGND | DGND | GND_{domain}",
        examples=["GND", "AGND", "PGND", "DGND", "GND_SHIELD"],
        notes=(
            "GND is the primary chassis/digital ground. "
            "AGND for analog, PGND for power-stage, DGND for digital islands. "
            "All GND variants must be tied at a single star point."
        ),
    ),
    NetNamePolicy(
        category="reset",
        pattern="nRST | /RST | RESET_n | MCU_RESET",
        examples=["nRST", "/RST", "SYS_RESET_n", "MCU_RESET"],
        notes=(
            "Active-low reset nets use 'n' prefix or '_n' suffix. Avoid bare 'RESET' — it is ambiguous about polarity."
        ),
    ),
    NetNamePolicy(
        category="clock",
        pattern="{DOMAIN}_CLK | CLK_{FREQ}",
        examples=["SYS_CLK", "I2C_SCL", "SPI_SCK", "CLK_32K", "CLK_48M"],
        notes=("Append the domain or frequency. I2C clock is always SCL (not CLK). SPI clock is SCK."),
    ),
    NetNamePolicy(
        category="i2c",
        pattern="I2C{N}_SDA | I2C{N}_SCL",
        examples=["I2C1_SDA", "I2C1_SCL", "I2C_SDA", "I2C_SCL"],
        notes=(
            "Suffix with bus index when multiple I2C buses exist. "
            "Do not use 'I2C_DATA' or 'I2C_CLOCK' — industry standard is SDA/SCL."
        ),
    ),
    NetNamePolicy(
        category="spi",
        pattern="SPI{N}_{SIGNAL}  (SIGNAL: SCK, MOSI, MISO, CS_{DEVICE})",
        examples=["SPI1_SCK", "SPI1_MOSI", "SPI1_MISO", "SPI1_CS_FLASH", "SPI2_CS_ADC"],
        notes=(
            "Each SPI device gets its own CS net with a device suffix. "
            "Never share CS nets. Use SPI_NSS only for single-device buses."
        ),
    ),
    NetNamePolicy(
        category="uart",
        pattern="UART{N}_TX | UART{N}_RX | UART{N}_RTS | UART{N}_CTS",
        examples=["UART1_TX", "UART1_RX", "UART2_TX", "UART2_RX", "UART1_RTS"],
        notes=("TX/RX named from the MCU's perspective. Cross the lines at the connector, not in the net name."),
    ),
    NetNamePolicy(
        category="usb",
        pattern="USB_{SPEED}_DP | USB_{SPEED}_DM | VBUS | USB_ID",
        examples=["USB_FS_DP", "USB_FS_DM", "USB_SS_DP0", "USB_SS_DM0", "VBUS", "USB_ID"],
        notes=("DP = D+, DM = D−. Add 'FS' (Full-Speed) or 'SS' (SuperSpeed) prefix. VBUS is always a power net."),
    ),
    NetNamePolicy(
        category="gpio",
        pattern="{FUNCTION} | MCU_{PORT}{PIN} | GPIO_{N}",
        examples=["LED_RED", "BTN_USER", "MCU_PA5", "GPIO_0", "SD_DET"],
        notes=(
            "Name by function, not by MCU pin number, wherever possible. "
            "Use MCU_PA5 only when no functional name is obvious."
        ),
    ),
    NetNamePolicy(
        category="analog",
        pattern="{DOMAIN}_AIN{N} | ADC{N}_IN | {SENSOR}_OUT",
        examples=["TEMP_AIN0", "ADC1_IN6", "VBAT_SENSE", "CURRENT_SENSE", "PHOTO_OUT"],
        notes=(
            "Suffix with '_SENSE' for divided/filtered versions of power rails. "
            "Keep analog net names short — long names cause schematic clutter."
        ),
    ),
    NetNamePolicy(
        category="pwm",
        pattern="{LOAD}_PWM | TIM{N}_CH{M}_PWM",
        examples=["FAN_PWM", "LED_PWM", "TIM1_CH1_PWM", "MOTOR_PWM"],
        notes="Name by the load being driven, not by the timer channel alone.",
    ),
    NetNamePolicy(
        category="interrupt",
        pattern="{DEVICE}_INT_n | {DEVICE}_nINT | {DEVICE}_ALERT",
        examples=["IMU_INT1_n", "TOUCH_nINT", "ACCEL_ALERT", "RTC_INT_n"],
        notes=(
            "Active-low interrupt nets always end with '_n' or start with 'n'. "
            "Use '_ALERT' for level-triggered open-drain alert lines."
        ),
    ),
]


def canonical_net_name(signal_type: str, **params: str) -> str:
    """Return a canonical net name for a signal type.

    Args:
        signal_type: One of ``"power"``, ``"ground"``, ``"clock"``,
            ``"i2c_sda"``, ``"i2c_scl"``, ``"spi_sck"``, ``"spi_mosi"``,
            ``"spi_miso"``, ``"spi_cs"``, ``"uart_tx"``, ``"uart_rx"``,
            ``"usb_dp"``, ``"usb_dm"``, ``"reset"``, ``"gpio"``.
        **params: Signal-specific parameters (see each type below).

    ``"power"`` params: ``rail`` (e.g. ``"+3V3"``).
    ``"ground"`` params: ``domain`` (optional, e.g. ``"A"`` → ``"AGND"``).
    ``"i2c_sda"`` / ``"i2c_scl"`` params: ``bus`` (optional, e.g. ``"1"``).
    ``"spi_sck"`` / ``"spi_mosi"`` / ``"spi_miso"`` params: ``bus`` (optional).
    ``"spi_cs"`` params: ``bus`` (optional), ``device`` (required).
    ``"uart_tx"`` / ``"uart_rx"`` params: ``bus`` (optional).
    ``"usb_dp"`` / ``"usb_dm"`` params: ``speed`` (e.g. ``"FS"``).
    ``"clock"`` params: ``domain`` (required).
    ``"reset"`` params: ``active_low`` (``"true"``/``"false"``).
    ``"gpio"`` params: ``function`` (required).
    """
    t = signal_type.lower().strip()
    if t == "power":
        return params.get("rail", "VCC").upper()
    if t == "ground":
        domain = params.get("domain", "")
        return f"{domain.upper()}GND" if domain else "GND"
    if t == "i2c_sda":
        bus = params.get("bus", "")
        return f"I2C{bus}_SDA" if bus else "I2C_SDA"
    if t == "i2c_scl":
        bus = params.get("bus", "")
        return f"I2C{bus}_SCL" if bus else "I2C_SCL"
    if t == "spi_sck":
        bus = params.get("bus", "")
        return f"SPI{bus}_SCK" if bus else "SPI_SCK"
    if t == "spi_mosi":
        bus = params.get("bus", "")
        return f"SPI{bus}_MOSI" if bus else "SPI_MOSI"
    if t == "spi_miso":
        bus = params.get("bus", "")
        return f"SPI{bus}_MISO" if bus else "SPI_MISO"
    if t == "spi_cs":
        bus = params.get("bus", "")
        device = params.get("device", "DEV")
        prefix = f"SPI{bus}" if bus else "SPI"
        return f"{prefix}_CS_{device.upper()}"
    if t == "uart_tx":
        bus = params.get("bus", "")
        return f"UART{bus}_TX" if bus else "UART_TX"
    if t == "uart_rx":
        bus = params.get("bus", "")
        return f"UART{bus}_RX" if bus else "UART_RX"
    if t == "usb_dp":
        speed = params.get("speed", "FS").upper()
        return f"USB_{speed}_DP"
    if t == "usb_dm":
        speed = params.get("speed", "FS").upper()
        return f"USB_{speed}_DM"
    if t == "clock":
        domain = params.get("domain", "SYS").upper()
        return f"{domain}_CLK"
    if t == "reset":
        active_low = params.get("active_low", "true").lower() in ("true", "1", "yes")
        return "nRST" if active_low else "RESET"
    if t == "gpio":
        func = params.get("function", "GPIO").upper()
        return _INVALID_CHARS_RE.sub("_", func)
    raise ValueError(f"Unknown signal_type '{signal_type}'")


def validate_net_name(name: str) -> list[str]:
    """Check a net name for common naming policy violations.

    Returns a list of human-readable problem strings; empty list means clean.
    """
    problems: list[str] = []
    if not name:
        problems.append("Net name is empty")
        return problems
    if _LEADING_DIGIT_RE.match(name):
        problems.append(f"Net name '{name}' starts with a digit (not allowed in most EDA tools)")
    if _INVALID_CHARS_RE.search(name):
        bad = set(_INVALID_CHARS_RE.findall(name))
        problems.append(f"Net name '{name}' contains invalid characters: {sorted(bad)}")
    if name.lower().startswith("net-(") or name.lower().startswith("net_"):
        problems.append(f"Net name '{name}' looks auto-generated; replace with a functional name")
    if len(name) > 64:
        problems.append(f"Net name '{name}' exceeds 64 characters — shorten it")
    return problems
