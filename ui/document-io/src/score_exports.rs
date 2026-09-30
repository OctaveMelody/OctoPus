use std::sync::Arc;

use image::codecs::jpeg::JpegEncoder;
use image::ExtendedColorType;
use krilla::geom::Size as PdfSize;
use krilla::page::PageSettings;
use krilla::Document;
use krilla_svg::{SurfaceExt, SvgSettings};
use resvg::tiny_skia::{Color, Pixmap, Transform};
use resvg::usvg;

use crate::file_exports::{MAX_EXPORT_BYTES, MAX_EXPORT_FILES};
use crate::DocumentIoError;

const SVG_PIXELS_PER_INCH: f64 = 96.0;
const PDF_POINTS_PER_INCH: f64 = 72.0;
const MAX_EXPORT_PAGE_PIXELS: u64 = 40_000_000;
const MAX_EXPORT_BATCH_PIXELS: u64 = 200_000_000;
const MAX_PDF_PAGE_POINTS: f32 = 14_400.0;
const JPEG_QUALITY: u8 = 95;

pub fn export_pdf(svg_pages: &[String]) -> Result<Vec<u8>, DocumentIoError> {
    export_pdf_with_options(svg_pages, svg_options())
}

fn export_pdf_with_options(
    svg_pages: &[String],
    options: usvg::Options<'_>,
) -> Result<Vec<u8>, DocumentIoError> {
    validate_svg_pages(svg_pages)?;
    let mut document = Document::new();

    for svg in svg_pages {
        let tree = parse_svg(svg, &options)?;
        let svg_size = tree.size();
        let scale = (PDF_POINTS_PER_INCH / SVG_PIXELS_PER_INCH) as f32;
        let width = svg_size.width() * scale;
        let height = svg_size.height() * scale;
        if !width.is_finite()
            || !height.is_finite()
            || width > MAX_PDF_PAGE_POINTS
            || height > MAX_PDF_PAGE_POINTS
        {
            return Err(DocumentIoError::ExportPageTooLarge);
        }
        let page_size =
            PdfSize::from_wh(width, height).ok_or(DocumentIoError::InvalidExportPage)?;
        let mut page = document.start_page_with(PageSettings::new(page_size));
        let mut surface = page.surface();
        surface
            .draw_svg(&tree, page_size, SvgSettings::default())
            .ok_or(DocumentIoError::ExportConversionFailed)?;
        surface.finish();
        page.finish();
    }

    let pdf = document
        .finish()
        .map_err(|_| DocumentIoError::ExportConversionFailed)?;
    if pdf.len() > MAX_EXPORT_BYTES {
        return Err(DocumentIoError::ExportTooLarge);
    }
    Ok(pdf)
}

pub fn export_jpg_pages(svg_pages: &[String], dpi: u16) -> Result<Vec<Vec<u8>>, DocumentIoError> {
    validate_svg_pages(svg_pages)?;
    if !matches!(dpi, 96 | 300) {
        return Err(DocumentIoError::InvalidExportDpi);
    }

    let options = svg_options();
    let mut total_pixels = 0_u64;
    let mut total_bytes = 0_usize;
    let mut outputs = Vec::with_capacity(svg_pages.len());
    for svg in svg_pages {
        let tree = parse_svg(svg, &options)?;
        let (width, height) = raster_dimensions(tree.size(), dpi)?;
        let page_pixels = u64::from(width) * u64::from(height);
        total_pixels = total_pixels
            .checked_add(page_pixels)
            .filter(|pixels| *pixels <= MAX_EXPORT_BATCH_PIXELS)
            .ok_or(DocumentIoError::ExportPageTooLarge)?;
        let pixmap = render_jpg_page(&tree, width, height, dpi)?;
        let bytes = encode_jpeg(pixmap, width, height)?;
        total_bytes = total_bytes
            .checked_add(bytes.len())
            .filter(|size| *size <= MAX_EXPORT_BYTES)
            .ok_or(DocumentIoError::ExportTooLarge)?;
        outputs.push(bytes);
    }
    Ok(outputs)
}

fn validate_svg_pages(svg_pages: &[String]) -> Result<(), DocumentIoError> {
    if svg_pages.is_empty() || svg_pages.iter().any(String::is_empty) {
        return Err(DocumentIoError::EmptyExport);
    }
    if svg_pages.len() > MAX_EXPORT_FILES {
        return Err(DocumentIoError::TooManyExportFiles);
    }
    let total_bytes = svg_pages
        .iter()
        .try_fold(0_usize, |total, svg| total.checked_add(svg.len()));
    if !total_bytes.is_some_and(|bytes| bytes <= MAX_EXPORT_BYTES) {
        return Err(DocumentIoError::ExportTooLarge);
    }
    Ok(())
}

fn svg_options() -> usvg::Options<'static> {
    let release = !cfg!(debug_assertions)
        || std::env::var("OCTOPUS_FONT_PROFILE").as_deref() == Ok("release");
    svg_options_for_profile(release)
}

fn svg_options_for_profile(release: bool) -> usvg::Options<'static> {
    let mut font_database = usvg::fontdb::Database::new();
    {
        const FACES: &[&[u8]] = &[
            include_bytes!("../../../src/octopus/assets/fonts/NotoSansSC-Regular.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/NotoSansSC-Bold.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/NotoSerifSC-Regular.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/NotoSerifSC-Bold.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/LiberationSans-Regular.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/LiberationSans-Bold.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/LiberationSans-Italic.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/LiberationSans-BoldItalic.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/LXGWWenKai-Regular.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/SimZhiSong.ttf"),
            include_bytes!("../../../src/octopus/assets/fonts/LXGWNeoXiHei.ttf"),
        ];
        for face in FACES {
            font_database.load_font_data(face.to_vec());
        }
        font_database.set_sans_serif_family("Noto Sans SC");
        font_database.set_serif_family("Noto Serif SC");
    }
    if !release || cfg!(target_os = "windows") {
        font_database.load_system_fonts();
    }
    usvg::Options {
        font_family: if release {
            "Noto Sans SC".into()
        } else {
            "Times New Roman".into()
        },
        fontdb: Arc::new(font_database),
        ..Default::default()
    }
}

fn parse_svg(svg: &str, options: &usvg::Options<'_>) -> Result<usvg::Tree, DocumentIoError> {
    let document =
        usvg::roxmltree::Document::parse(svg).map_err(|_| DocumentIoError::InvalidExportPage)?;
    if document
        .descendants()
        .any(|node| node.is_element() && matches!(node.tag_name().name(), "image" | "filter"))
    {
        return Err(DocumentIoError::UnsupportedExportFeature);
    }
    usvg::Tree::from_xmltree(&document, options).map_err(|_| DocumentIoError::InvalidExportPage)
}

fn raster_dimensions(size: usvg::Size, dpi: u16) -> Result<(u32, u32), DocumentIoError> {
    let scale = f64::from(dpi) / SVG_PIXELS_PER_INCH;
    let width = (f64::from(size.width()) * scale).round();
    let height = (f64::from(size.height()) * scale).round();
    if !width.is_finite()
        || !height.is_finite()
        || width < 1.0
        || height < 1.0
        || width > f64::from(u32::MAX)
        || height > f64::from(u32::MAX)
    {
        return Err(DocumentIoError::InvalidExportPage);
    }
    let (width, height) = (width as u32, height as u32);
    let page_pixels = u64::from(width)
        .checked_mul(u64::from(height))
        .filter(|pixels| *pixels <= MAX_EXPORT_PAGE_PIXELS)
        .ok_or(DocumentIoError::ExportPageTooLarge)?;
    if page_pixels == 0 {
        return Err(DocumentIoError::InvalidExportPage);
    }
    Ok((width, height))
}

fn render_jpg_page(
    tree: &usvg::Tree,
    width: u32,
    height: u32,
    dpi: u16,
) -> Result<Pixmap, DocumentIoError> {
    let mut pixmap = Pixmap::new(width, height).ok_or(DocumentIoError::ExportPageTooLarge)?;
    pixmap.fill(Color::WHITE);
    let scale = f32::from(dpi) / SVG_PIXELS_PER_INCH as f32;
    resvg::render(
        tree,
        Transform::from_scale(scale, scale),
        &mut pixmap.as_mut(),
    );
    Ok(pixmap)
}

fn encode_jpeg(pixmap: Pixmap, width: u32, height: u32) -> Result<Vec<u8>, DocumentIoError> {
    let mut pixels = pixmap.take();
    let pixel_count = (u64::from(width) * u64::from(height)) as usize;
    for index in 0..pixel_count {
        let source = index * 4;
        let target = index * 3;
        let (red, green, blue) = (pixels[source], pixels[source + 1], pixels[source + 2]);
        pixels[target] = red;
        pixels[target + 1] = green;
        pixels[target + 2] = blue;
    }
    pixels.truncate(pixel_count * 3);

    let mut encoded = Vec::new();
    JpegEncoder::new_with_quality(&mut encoded, JPEG_QUALITY)
        .encode(&pixels, width, height, ExtendedColorType::Rgb8)
        .map_err(|_| DocumentIoError::ExportConversionFailed)?;
    Ok(encoded)
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use image::codecs::jpeg::JpegDecoder;
    use image::ImageDecoder;

    use super::{export_jpg_pages, export_pdf};
    use crate::DocumentIoError;

    const SVG_PAGE: &str = r##"
        <svg xmlns="http://www.w3.org/2000/svg" width="100" height="60" viewBox="0 0 100 60">
            <path d="M 10 10 L 90 10 L 50 50 Z" fill="#000000"/>
            <text x="20" y="55" font-family="Microsoft YaHei" font-size="10">简谱你好</text>
        </svg>
    "##;

    fn page() -> Vec<String> {
        vec![SVG_PAGE.to_owned()]
    }

    #[test]
    fn release_database_includes_fallback_faces() {
        let options = super::svg_options_for_profile(true);
        if !cfg!(target_os = "windows") {
            assert_eq!(options.fontdb.faces().count(), 11);
        }
        let families: Vec<_> = options
            .fontdb
            .faces()
            .flat_map(|face| face.families.iter().map(|family| family.0.as_str()))
            .collect();
        assert!(families.contains(&"Noto Sans SC"));
        assert!(families.contains(&"Noto Serif SC"));
        assert!(families.contains(&"Liberation Sans"));
        assert!(families.contains(&"LXGW WenKai"));
        assert!(families.contains(&"SimZhiSong"));
        assert!(families.contains(&"LXGW Neo XiHei"));
        if !cfg!(target_os = "windows") {
            assert!(!families.contains(&"Microsoft YaHei"));
        }
        let svg = SVG_PAGE.replace("Microsoft YaHei", "Noto Sans SC");
        let pdf = super::export_pdf_with_options(&[svg], options).unwrap();
        assert!(pdf
            .windows(b"/ToUnicode".len())
            .any(|item| item == b"/ToUnicode"));
        assert!(pdf
            .windows(b"/FontFile".len())
            .any(|item| item == b"/FontFile"));
    }

    #[test]
    fn exports_multiple_vector_pdf_pages_with_embedded_text_resources() {
        let pdf = export_pdf(&vec![SVG_PAGE.to_owned(); 5]).unwrap();
        let page_marker = b"/Type/Page/";

        assert!(pdf.starts_with(b"%PDF-"));
        assert_eq!(
            pdf.windows(page_marker.len())
                .filter(|window| *window == page_marker)
                .count(),
            5
        );
        assert!(pdf
            .windows(b"/MediaBox[0 0 75 45]".len())
            .any(|item| item == b"/MediaBox[0 0 75 45]"));
        assert!(pdf
            .windows(b"/ToUnicode".len())
            .any(|item| item == b"/ToUnicode"));
        assert!(pdf
            .windows(b"/FontFile".len())
            .any(|item| item == b"/FontFile"));
        assert!(!pdf
            .windows(b"/Subtype/Image".len())
            .any(|item| item == b"/Subtype/Image"));
    }

    #[test]
    fn exports_jpg_at_intrinsic_and_300_dpi_sizes_with_white_background() {
        for (dpi, expected) in [(96, (100, 60)), (300, (313, 188))] {
            let images = export_jpg_pages(&page(), dpi).unwrap();
            let decoder = JpegDecoder::new(Cursor::new(&images[0])).unwrap();
            let (width, height) = decoder.dimensions();
            let mut rgb = vec![0; decoder.total_bytes() as usize];
            decoder.read_image(&mut rgb).unwrap();
            let corner = &rgb[0..3];
            let (pixels, remainder) = rgb.as_chunks::<3>();
            assert!(remainder.is_empty());
            let (mut rightmost_ink, mut bottommost_ink) = (0, 0);
            for (index, pixel) in pixels.iter().enumerate() {
                if pixel.iter().all(|channel| *channel < 128) {
                    rightmost_ink = rightmost_ink.max(index as u32 % width);
                    bottommost_ink = bottommost_ink.max(index as u32 / width);
                }
            }

            assert_eq!((width, height), expected);
            assert!(corner.iter().all(|channel| *channel >= 250));
            assert!(
                rightmost_ink > width * 3 / 4,
                "ink ends at x={rightmost_ink}"
            );
            assert!(
                bottommost_ink > height * 3 / 4,
                "ink ends at y={bottommost_ink}"
            );
            assert!(images[0].starts_with(&[0xff, 0xd8]));
        }
    }

    #[test]
    fn rejects_invalid_resolution_pages_and_resource_usage() {
        assert!(matches!(
            export_jpg_pages(&page(), 150),
            Err(DocumentIoError::InvalidExportDpi)
        ));
        assert!(matches!(
            export_jpg_pages(&["not svg".into()], 96),
            Err(DocumentIoError::InvalidExportPage)
        ));
        let filtered = r#"
            <svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">
                <filter id="f"/>
            </svg>
        "#;
        assert!(matches!(
            export_jpg_pages(&[filtered.into()], 96),
            Err(DocumentIoError::UnsupportedExportFeature)
        ));
        let oversized = r#"<svg xmlns="http://www.w3.org/2000/svg" width="8000" height="6000"/>"#;
        assert!(matches!(
            export_jpg_pages(&[oversized.into()], 96),
            Err(DocumentIoError::ExportPageTooLarge)
        ));
        assert!(matches!(export_pdf(&[]), Err(DocumentIoError::EmptyExport)));
    }
}
