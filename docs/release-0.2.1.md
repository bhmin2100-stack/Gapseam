# GFE 0.2.1

## SFO3.1 process application

An existing local recipe named SFO3.1 could shadow the shipped reference with
different coefficients, including GPC 10 and disabled etch/redeposition.
Registration failures could also leave only the generic default recipe visible.
The SFO3.1 menu entry now reads the recipe bundled with the application directly,
so it works independently of the local recipe library. A changed same-name user
recipe remains accessible as SFO3.1 (저장본); applying the built-in entry never
rewrites or deletes it. Applying checks the resulting core settings before
reporting success.

1. In `3 진행`, open `내 조건 · 불러오기 / 저장` and select `SFO3.1`.
2. Click `파라미터 적용`. GPC must become 0.560 Å/cycle and etch, redeposition,
   and inhibition must be ON.
3. Set the desired ALD cycles and click `시뮬레이션 실행`.

The existing structure and cycle count remain by default. To load the reference
1045 cycles, enable the saved-cycle checkbox before applying. Cycles remain
editable afterward. Structure selection stays in `1 구조`.

The fixed-repeat coefficients and numerical solver are unchanged. This release
fixes recipe loading and packaging; it is not a new physical calibration.
