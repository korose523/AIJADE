# 艾娅德 (Aijade-9) — character image

The companion's look, from the author's own design references in the 历史文档 folder (`reference/`, copied unchanged), and
the character bible (AIJADE v9 角色背景设计文档).

Appearance: long, straight platinum-blonde hair with bangs and an ahoge; a white frilled maid headdress; a black bow on one
side; blue eyes; diamond-shaped earrings; a black choker with a white frill and a black ribbon; a black corset maid dress with
a white frilled apron and black bows; black arm bands with white frills; black thigh-high stockings; black strap shoes.

Derived assets:

- `src/Aijade.Web/wwwroot/icons/*` and `favicon.ico`: the face is cropped from `reference/1a0a996be5676.png` (which has a
  real alpha channel) and composed over a soft blue gradient:

  ```bash
  sips -c 330 330 --cropOffset 0 345 reference/1a0a996be5676.png --out face.png
  swiftc -O tools/compose.swift -o compose
  ./compose face.png web-app-manifest-512x512.png 512 0      # also 192 and 180 (apple-touch-icon)
  ./compose face.png maskable_icon_x512.png 512 0.1          # inset for the maskable safe zone
  ./compose face.png icon-48.png 48 0 && sips -s format ico icon-48.png --out favicon.ico
  ```

- `src/Aijade.UI/wwwroot/stage.js`: the built-in procedural avatar is drawn after the same features.
