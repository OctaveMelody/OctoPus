# Offline OCR profiles

OctoPus uses RapidOCR 3.10.0 with ONNX Runtime 1.30.0 and
`opencv-python-headless==5.0.0.93`. Headless removes OpenCV's GUI support; `cv2`,
NumPy, Shapely and the other required dependencies remain. It is not an OpenCV-free
build. Do not install regular or contrib OpenCV alongside the headless distribution.

## Model selection

| Program Settings | Detection | Recognition | Orientation |
|---|---|---|---|
| Default (Faster) / 默认（更快） | PP-OCRv6 Small | PP-OCRv6 Small | PP-OCRv4 Mobile |
| Accuracy (Slower) / 高精度（较慢） | PP-OCRv6 Medium | PP-OCRv6 Medium | Same shared classifier |

The earlier RapidOCR 3.9.2 implementation used the Small profile. Its three weights
are unchanged in this upgrade. Dependency replacement alone is not an accuracy claim.
Both profiles use multilingual weights for English and Chinese; they do not remove
other supported languages from those weights. No separate English model is bundled.

The saved choice is captured when New or Append starts. Every page and crop uses that
choice. Changing settings during a job affects the next job and does not modify JPS.
The cache retains one active profile, releasing it before loading another. Switching
can add loading time. Larger text models need more time and memory and may help difficult
text; some scores can perform better with Default. Musical geometry and manual review
remain necessary in either mode.

## Pinned inventory

The machine-readable source of truth is
[manifest.json](../src/octopus/assets/ocr_models/manifest.json). It records exact bytes,
SHA-256 checksums, versioned official download URLs and profile membership.

| File | Bytes | Used by |
|---|---:|---|
| PP-OCRv6_det_small.onnx | 9,929,594 | Default |
| PP-OCRv6_rec_small.onnx | 21,234,383 | Default |
| PP-OCRv6_det_medium.onnx | 62,119,454 | Accuracy |
| PP-OCRv6_rec_medium.onnx | 76,629,984 | Accuracy |
| ch_ppocr_mobile_v2.0_cls_mobile.onnx | 585,532 | Both |

Default uses 31,749,509 bytes (~30.3 MiB). Accuracy uses 139,334,970 bytes (~132.9 MiB).
The combined five-file set is 170,498,947 bytes (~162.6 MiB), adding 138,749,438 bytes
(~132.3 MiB) before compression to the previous three-file payload. Compressed package
size must be measured separately; model growth can outweigh headless dependency savings.

## Setup and packaging

`python3 scripts/prepare_ocr_models.py` verifies or obtains the pinned files in ignored
`build/ocr-model-cache`. Downloads belong to setup/build preparation. Model binaries are
not committed. An existing cache is accepted only after size and checksum verification.
Keep the adjacent manifest, license and attribution notices with the weights.

Source execution resolves verified local assets. `OCTOPUS_OCR_MODEL_DIR` can explicitly
select a prepared model directory for an isolated source installation or evidence run.
The packaged worker uses local staged files; it must not need an external model cache
or runtime download. Missing or corrupt selected assets fail clearly. Accuracy never
silently becomes Default.

Production packaging stages exactly the five selected ONNX files, shares the classifier,
and removes duplicate dependency weights and ONNX Runtime example models. Keep the full
portable directory together. Windows requires native acceptance before release; Linux
validation does not establish native macOS packaging support.

## Attribution and evidence

Upstream model weights are attributed to Baidu and the applicable PaddleOCR rights
holders; RapidAI/RapidOCR supplies ONNX conversion and packaging. The adjacent
[notice](../src/octopus/assets/ocr_models/NOTICE.md) records provenance and the
[Apache-2.0 license](../src/octopus/assets/ocr_models/LICENSE) is retained with the assets.
The official [RapidOCR model notice](https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.10.0/python/MODEL_LICENSES.md)
enumerates Small and classifier artifacts. Medium provenance is also supported by the
official [detector card](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det) and
[ONNX recognizer card](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec_onnx).

Evaluation records must identify mode, actual selected model hashes, effective settings,
runtime versions and execution providers. Historical fixtures remain historical;
switching model/configuration requires a distinct fixture namespace and invalidates
incompatible resume evidence. Corpus label alignment is diagnostic: compare changed
readings with the printed source, including navigation marks absent from manual labels.
