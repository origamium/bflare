# bflare

[日本語](#日本語) | [English](#english)

---

## 日本語

Blender のコンポジターで動く、ポストエフェクトとレンズ再現のアドオンです。
ブルーム、フレア、回折、色収差、ビネット、グレーディングをひとつのチェーンにまとめています。被写界深度は、レンズの瞳から計算します。
ビューポートでもレンダーでも同じ見た目になります。

### 主な機能

- **ルック**: Neutral / Soft Film / Cinematic / Night Neon / Vintage Lens の 5 種類のプリセット。
- **レンズプロファイル**: 実在レンズ 11 本ぶん。歪曲・周辺減光（絞りごと）・絞り羽根の枚数と形を、レビューサイトの実測値をもとに設定しています。
- **光学的な被写界深度**:
  - 球面収差、軸上色収差、口径食（キャッツアイ）
  - 絞り羽根の枚数・曲率・回転、玉ねぎボケ、アポダイゼーション、中央遮蔽（ミラーレンズ）
  - 前ボケは別レイヤーで処理するので、手前の物体の輪郭が汚れにくくなっています
- **回折**: 絞りの形からフラウンホーファー回折の光条を計算し、波長ごとに積分します。
- **アナモルフィック**: ボケの縦横比、フレアストリーク（長さ・太さ・減衰・芯と先端の色・本数・間隔）、横方向の圧縮。
- **その他のエフェクト**: 露出、ブルーム、ストリーク、レンズゴースト、色収差グロー、ベーリングフレア、ホワイトバランス、カラーグレード、トーン、フィルムグレイン。
- **オン/オフ**: パネル見出しのチェックで、チェーンを外して軽くできます。設定は残ります。

### 動作環境

- Blender 5.3 以降（`scene.compositing_node_group` を使用）
- 追加のライブラリは不要です（Blender に同梱の NumPy を使います）

### インストール

1. `bflare.py` をダウンロードします。
2. Blender で *編集 > プリファレンス > アドオン* を開き、右上のメニューから *ディスクからインストール* を選んで、このファイルを指定します。
3. **bflare** を有効にします。

### 使い方

1. 3D ビューポートのサイドバー（`N`）で **bflare** タブを開きます。
2. **Build Chain** を押すと、シーンのコンポジターにエフェクトチェーンが作られます。
3. **Look** でルックを、**Lens** でレンズを選びます。
4. 被写界深度は **Depth of Field > Mode** を **Optical** にします。ピントはカメラの設定（フォーカス距離、または対象オブジェクト）に追従します。
5. ビューポートで見るには、**Viewport** を *Camera* か *Always* にします。カメラ視点で確認するのがおすすめです。

各エフェクトは、パネル内の見出しのチェックで個別にオン/オフできます。

### 重さについて

被写界深度は縮小したバッファで計算しています。幅の初期値は、ビューポートが 480px、レンダーが 960px です。
コストは幅のおよそ 4 乗で増えます。重いと感じたら **Quality** の値を下げてください。
シーン自体が重いときは、パネル見出しのチェックを外すとチェーンごと止まります。

### 制約

- 生成したカーネル画像はファイルに保存されません。ファイルを開いたときに作り直されます。
- 他のコンポジターノードグループがすでにシーンに設定されている場合、上書きはしません。
- `scene.compositing_node_group` は Blender 6.0 で非推奨になる予定です。

### ライセンス

[MIT](LICENSE)

レンズの製品名は、各社の商標または登録商標です。このアドオンは各メーカーとは関係がありません。プロファイルの数値は公開されているレビューの測定値にもとづく近似です。

---

## English

A post effect and lens simulation add-on for the Blender compositor.
It puts bloom, flares, diffraction, chromatic aberration, vignetting and grading into one chain, and computes depth of field from the lens pupil.
The viewport and the final render look the same.

### Features

- **Looks**: five presets: Neutral, Soft Film, Cinematic, Night Neon and Vintage Lens.
- **Lens profiles**: 11 real lenses. Distortion, vignetting per f-stop, and the number and shape of the aperture blades come from published lab measurements.
- **Optical depth of field**:
  - Spherical aberration, axial colour and cat's-eye vignetting.
  - Blade count, curvature and rotation, onion rings, apodization and central obstruction (mirror lenses).
  - The foreground blur runs on its own layer, so near objects keep clean edges.
- **Diffraction**: a Fraunhofer star computed from the aperture shape and integrated over wavelength.
- **Anamorphic**: bokeh squeeze, flare streaks (length, thickness, falloff, core and tip colour, line count, spacing) and horizontal squeeze.
- **Other effects**: exposure, bloom, streaks, lens ghosts, aberration glow, veiling flare, white balance, colour grade, tone and film grain.
- **On/off switch**: the checkbox in the panel header detaches the chain when the scene gets heavy. Every setting is kept.

### Requirements

- Blender 5.3 or later (uses `scene.compositing_node_group`).
- No extra packages. It uses the NumPy that ships with Blender.

### Installation

1. Download `bflare.py`.
2. In Blender, open *Edit > Preferences > Add-ons*, choose *Install from Disk* from the menu in the top right, and select the file.
3. Enable **bflare**.

### Usage

1. Open the **bflare** tab in the 3D Viewport sidebar (`N`).
2. Click **Build Chain**. This creates the effect chain as the scene's compositor.
3. Pick a look under **Look** and a lens under **Lens**.
4. For depth of field, set **Depth of Field > Mode** to **Optical**. Focus follows the camera's focus distance or focus object.
5. To see it in the viewport, set **Viewport** to *Camera* or *Always*. Looking through the camera works best.

Each effect has its own checkbox in its panel header.

### Performance

Depth of field is computed on a reduced buffer: 480 px wide in the viewport and 960 px in the render by default.
The cost grows roughly with the fourth power of the width, so lower the **Quality** values if it is slow.
If the scene itself is heavy, untick the panel header to stop the whole chain.

### Limitations

- Generated kernel images are not saved in the .blend. They are rebuilt when the file is opened.
- If the scene already uses another compositor node group, the add-on does not overwrite it.
- `scene.compositing_node_group` is due to be deprecated in Blender 6.0.

### License

[MIT](LICENSE)

Lens product names are trademarks or registered trademarks of their owners. This project is not affiliated with any manufacturer. Profile values are approximations based on published reviews.
