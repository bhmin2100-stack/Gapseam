# Emulator 06 - PECVD/PEALD Inhibition Deposition Plan

## Literature basis

- Talukdar, Girolami, and Abelson, JVST A 2019, "Seamless fill of deep trenches by chemical vapor deposition": consumable inhibitors with high sticking probability are depleted near the trench opening, suppress upper-surface bread-loaf growth while leaving deeper trench growth less inhibited. Source: https://girolami-group.chemistry.illinois.edu/publications/publications/J.%20Vac.%20Sci.%20Technol.%20A%202019%2C%2037%2C%20021509.pdf
- Knoops et al., JES 2010, "Conformality of plasma-assisted ALD": PEALD conformality in high-AR trenches depends on radical recombination probability, reaction probability, and diffusion; large recombination loss creates bottom/sidewall under-saturation before saturation. Source: https://research.tue.nl/en/publications/conformality-of-plasma-assisted-ald-physical-processes-and-modeli/
- Janssen et al., APL 2025, "Topographically selective ALD within trenches enabled by an amorphous carbon inhibition layer": aC inhibition can be applied selectively to top horizontal surfaces, so ALD continues inside trenches. Source: https://pure.tue.nl/ws/portalfiles/portal/353888092/063505_1_5.0246311.pdf
- Akiki et al., Applied Surface Science 2020 / JVST A 2021: area-selective PECVD using Ar/SiF4/H2 shows silicon deposition on SiNx/SiOxNy while AlOx is blocked by fluorination/Al-F bonding; this supports representing PECVD inhibition as a surface blocking field. Source: https://www.sciencedirect.com/science/article/pii/S0169433220320626
- Vallee et al., JVST A 2020: ions in PECVD and PEALD tune plasma-surface reactions, but high ion energy can damage or sputter; low-energy ion assistance is the relevant direction for smooth emulator behavior. Source: https://colab.ws/articles/10.1116%2F1.5140841

## Emulator decision

Use a fast analytic coverage field instead of Monte Carlo particle transport:

1. Compute an inhibitor coverage field that is high at the top/opening and decays with depth.
2. Convert coverage to growth ratio: high coverage means low local deposition.
3. Add a mild PEALD radical recombination attenuation term for the hybrid mode.
4. Add a bounded bottom boost so the shape reads as bottom-favored fill rather than pure conformal coating.
5. Smooth the ratio field along the surface before propagation to avoid spiky/toothed profiles.

This is O(N) per substep and reuses the existing vertex-normal propagation plus topology cleanup path from Emulator 05.

## Implemented default

- Slot: 06 - Inhibition Deposition Fill
- Kernel: `inhibition_weighted_deposition`
- Default process: `hybrid`
- Default inhibition: 85% top/opening suppression, about 1100 A penetration depth, 8% minimum growth floor, 20% bottom boost, 35% PEALD recombination weighting, 45 A smoothing.

## Known simplifications

- No full ballistic Markov-chain transport.
- No explicit inhibitor adsorption/desorption state variable between cycles.
- No ion-energy damage or sputter coupling.
- PEALD radical recombination is represented as a smooth attenuation factor, not a radical density solver.
