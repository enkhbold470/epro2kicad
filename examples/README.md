# Example: Daaga V1.3

`Daaga1.3V.epro` is a real EasyEDA Pro export — a sumo-robot controller board
(Arduino Nano, TB6612FNG dual motor driver, QRE1113 reflective sensors,
HC-05 Bluetooth header) designed in 2020.

Convert it:

```bash
python3 ../epro2kicad.py Daaga1.3V.epro --zip
```

Expected output: 45 footprints, 1068 tracks, 63 nets.
`daaga_board_top.png` is a `kicad-cli pcb render` of the converted board.
