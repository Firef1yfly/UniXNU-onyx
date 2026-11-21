# Local SM8735 profile ownership

This directory owns only confirmed shared CPU/GIC/timer/PSCI bindings, the SoC config fragment and SoC patch order. Read ../AGENTS.md, ../docs/STOCK-IMAGES.md, README.md and upstream SoC/device-tree guides before changes. Keep RAM, board reservations, enabled peripherals and firmware policy in the device repository. Do not infer runtime facts from static stock images or copy SM8550/luming addresses. Update the device porting record with relevant changes; retain build gates until the hardware evidence is complete.
