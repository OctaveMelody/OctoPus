# Third-party notices

OctoPus bundles OCR components with its desktop worker. The complete Apache License, Version
2.0 text is included at [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt).

## RapidOCR and bundled OCR models

The optional **RapidOCR + ONNX** provider packages RapidOCR 3.9.2 and its default ONNX models.
The RapidOCR project identifies its engineering code as Apache-2.0 and states that the bundled
OCR models originate from PaddleOCR; the model copyright belongs to Baidu and/or the applicable
PaddleOCR rights holders. RapidOCR's tagged 3.9.2 README records those attributions, and the
current upstream model-license notice documents the applicable model terms. The default models
in the pinned wheel are:

| Bundled model | SHA-256 |
| --- | --- |
| `PP-OCRv6_det_small.onnx` | `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f` |
| `PP-OCRv6_rec_small.onnx` | `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` |
| `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |

RapidOCR source and release references:

- [RapidOCR 3.9.2 README and project license](https://github.com/RapidAI/RapidOCR/blob/v3.9.2/README.md)
- [RapidOCR model license and attribution notice](https://github.com/RapidAI/RapidOCR/blob/main/python/MODEL_LICENSES.md)
- [RapidOCR 3.9.2 default ONNX model registry](https://github.com/RapidAI/RapidOCR/blob/v3.9.2/python/rapidocr/default_models.yaml)
- [PaddleOCR upstream](https://github.com/PaddlePaddle/PaddleOCR)

The compatibility **rapidocr-onnxruntime** provider uses the Apache-2.0-licensed RapidOCR
implementation. The Apache license copy above applies to both RapidOCR packages and the models
described here.

## ONNX Runtime

Both providers use ONNX Runtime 1.30.0, licensed under MIT. The distribution includes its
license and third-party notices with the worker when collected from the pinned package. Source:
[ONNX Runtime 1.30.0](https://github.com/microsoft/onnxruntime/tree/v1.30.0).

