# Offline OCR model

OctoPus uses RapidOCR 3.10.0 with ONNX Runtime 1.30.0 and
`opencv-python-headless==5.0.0.93`. Headless OpenCV removes GUI support; `cv2`, NumPy,
Shapely and the other required dependencies remain. Do not install regular or contrib
OpenCV alongside the headless distribution.

## Active profile

The product has one OCR profile: Default. It uses PP-OCRv6 Small for text detection and
recognition, with the shared PP-OCRv4 Mobile orientation classifier. All three models use
multilingual weights that support English and Chinese; no separate English model is bundled.
CPU execution retains 2 intra-op and 1 inter-op threads.

## Pinned inventory

The machine-readable source of truth is
[manifest.json](../src/octopus/assets/ocr_models/manifest.json). It records exact bytes,
SHA-256 checksums, versioned official download URLs and the sole profile's model roles.

| File | Bytes |
|---|---:|
| PP-OCRv6_det_small.onnx | 9,929,594 |
| PP-OCRv6_rec_small.onnx | 21,234,383 |
| ch_ppocr_mobile_v2.0_cls_mobile.onnx | 585,532 |

The offline model payload is 31,749,509 bytes (about 30.3 MiB), before package compression.
Historical Medium-profile evaluations and complete packages remain audit evidence; they are
retired and are not selectable or staged by the current build path.

## Setup and packaging

`python3 scripts/prepare_ocr_models.py` verifies or obtains the pinned files in ignored
`build/ocr-model-cache`. Downloads belong to setup/build preparation. Model binaries are
not committed. An existing cache is accepted only after size and checksum verification.
Keep the adjacent manifest, license and attribution notices with the weights.

Source execution resolves verified local assets. `OCTOPUS_OCR_MODEL_DIR` can explicitly
select a prepared model directory for an isolated source installation or evidence run.
The packaged worker uses local staged files; it must not need an external model cache or
runtime download. Missing, corrupt or unexpected model assets fail clearly.

Production packaging stages exactly the three selected ONNX files and removes duplicate
dependency weights and ONNX Runtime example models. Keep the full portable directory
together. Windows requires native acceptance before release; Linux validation does not
establish native macOS packaging support.

## Attribution and evidence

Upstream model weights are attributed to Baidu and the applicable PaddleOCR rights holders;
RapidAI/RapidOCR supplies ONNX conversion and packaging. The adjacent
[notice](../src/octopus/assets/ocr_models/NOTICE.md) records provenance and the
[Apache-2.0 license](../src/octopus/assets/ocr_models/LICENSE) is retained with the assets.
The official [RapidOCR model notice](https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.10.0/python/MODEL_LICENSES.md)
enumerates the Small and classifier artifacts.

Current evaluation records identify the selected model hashes, effective settings, runtime
versions and execution providers. Historical fixtures and Medium evaluation reports remain
historical evidence. Current fixtures use only the Default profile and identity-scoped
request keys.
