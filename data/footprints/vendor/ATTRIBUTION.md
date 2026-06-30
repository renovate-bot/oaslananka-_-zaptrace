# Vendored footprint land patterns

These `.kicad_mod` files are **unmodified** land patterns copied from upstream,
peer-reviewed, datasheet-derived KiCad footprint libraries. They are vendored so
that module / DFN / LGA / aQFN / magjack packages — which have no parametric
IPC-7351 generator in ZapTrace — get real, verified pad geometry instead of
hand-transcribed coordinates (a single wrong coordinate is a fabrication hazard).

## License

All files here are licensed under **Creative Commons CC-BY-SA 4.0** with the
KiCad library exception: designs and generated manufacturing files that *use*
these land patterns are not considered adapted material, so boards produced with
ZapTrace are unaffected. The footprint files themselves remain under CC-BY-SA 4.0.

- License: https://creativecommons.org/licenses/by-sa/4.0/legalcode
- KiCad library license terms: https://www.kicad.org/libraries/license/

## Provenance

| File | Package | Used for | Source |
|------|---------|----------|--------|
| `Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.kicad_mod` | LGA-8 | BME280 | KiCad official library (`Package_LGA.pretty`) |
| `Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod` | DFN-8 | SHT31-DIS | KiCad official library (`Sensor_Humidity.pretty`) |
| `Nordic_AQFN-73-1EP_7x7mm_P0.5mm.kicad_mod` | aQFN-73 | nRF52840 | KiCad official library (`Package_DFN_QFN.pretty`) |
| `RJ45_Hanrun_HR911105A_Horizontal.kicad_mod` | RJ45 magjack | W5500 Ethernet jack | KiCad official library (`Connector_RJ.pretty`) |
| `ESP32-C3-MINI-1.kicad_mod` | module | ESP32-C3-MINI-1 | Espressif official KiCad library (`espressif/kicad-libraries`) |

The KiCad official library and the Espressif library publish under the same
CC-BY-SA 4.0 + exception terms. Files are kept verbatim; update them by copying a
newer upstream revision, not by editing in place.
