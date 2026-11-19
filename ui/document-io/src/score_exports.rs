use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use image::codecs::jpeg::{JpegEncoder, PixelDensity};
use image::ExtendedColorType;
use krilla::geom::Size as PdfSize;
use krilla::page::PageSettings;
use krilla::Document;
use krilla_svg::{SurfaceExt, SvgSettings};
use resvg::tiny_skia::{Color, Pixmap, Transform};
use resvg::usvg;

use crate::file_exports::{
    publish_generated_pages, ConfirmedExportTarget, ExportFormat, MAX_EXPORT_BYTES,
    MAX_EXPORT_FILES,
};
use crate::DocumentIoError;

const SVG_PIXELS_PER_INCH: f64 = 96.0;
const PDF_POINTS_PER_INCH: f64 = 72.0;
const MAX_EXPORT_PAGE_PIXELS: u64 = 40_000_000;
const MAX_PDF_PAGE_POINTS: f32 = 14_400.0;
pub const RASTER_EXPORT_DPI: u16 = 300;
const JPEG_QUALITY: u8 = 95;

pub fn export_pdf(svg_pages: &[String]) -> Result<Vec<u8>, DocumentIoError> {
    export_pdf_with_options(svg_pages, svg_options()?, false)
}

pub fn export_pdf_for_paper(svg_pages: &[String], paper: &str) -> Result<Vec<u8>, DocumentIoError> {
    export_pdf_with_options(svg_pages, svg_options()?, paper.eq_ignore_ascii_case("A5"))
}

fn export_pdf_with_options(
    svg_pages: &[String],
    options: usvg::Options<'_>,
    a5: bool,
) -> Result<Vec<u8>, DocumentIoError> {
    validate_svg_pages(svg_pages)?;
    let mut document = Document::new();

    for svg in svg_pages {
        let tree = parse_svg(svg, &options)?;
        let svg_size = tree.size();
        let scale = (PDF_POINTS_PER_INCH / SVG_PIXELS_PER_INCH) as f32;
        let svg_width = svg_size.width() * scale;
        let svg_height = svg_size.height() * scale;
        if !svg_width.is_finite()
            || !svg_height.is_finite()
            || svg_width > MAX_PDF_PAGE_POINTS
            || svg_height > MAX_PDF_PAGE_POINTS
        {
            return Err(DocumentIoError::ExportPageTooLarge);
        }
        // A5 uses the reference canvas while preserving the existing PDF page size.
        let width = if a5 { 709.0 * scale } else { svg_width };
        let height = if a5 { 1000.0 * scale } else { svg_height };
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

pub fn publish_raster_pages(
    selected_path: &Path,
    svg_pages: &[String],
    confirmed_existing: &[ConfirmedExportTarget],
    format: ExportFormat,
    dpi: u16,
) -> Result<Vec<PathBuf>, DocumentIoError> {
    validate_svg_pages(svg_pages)?;
    if dpi != RASTER_EXPORT_DPI {
        return Err(DocumentIoError::InvalidExportDpi);
    }
    let png = match format {
        ExportFormat::Png => true,
        ExportFormat::Jpg => false,
        _ => return Err(DocumentIoError::InvalidExportPath),
    };
    let options = svg_options()?;
    publish_generated_pages(
        selected_path,
        format,
        svg_pages.len(),
        confirmed_existing,
        |index| encode_raster_page(&svg_pages[index], &options, dpi, png),
    )
}

fn encode_raster_page(
    svg: &str,
    options: &usvg::Options<'_>,
    dpi: u16,
    png: bool,
) -> Result<Vec<u8>, DocumentIoError> {
    let tree = parse_svg(svg, options)?;
    let (width, height) = raster_dimensions(tree.size(), dpi)?;
    let pixmap = render_jpg_page(&tree, width, height, dpi)?;
    if !png {
        return encode_jpeg(pixmap, width, height, dpi);
    }
    let mut encoded = Vec::new();
    let mut encoder = png::Encoder::new(&mut encoded, width, height);
    encoder.set_color(png::ColorType::Rgba);
    encoder.set_depth(png::BitDepth::Eight);
    let pixels_per_meter = (u32::from(dpi) * 10_000 + 127) / 254;
    encoder.set_pixel_dims(Some(png::PixelDimensions {
        xppu: pixels_per_meter,
        yppu: pixels_per_meter,
        unit: png::Unit::Meter,
    }));
    let mut writer = encoder
        .write_header()
        .map_err(|_| DocumentIoError::ExportConversionFailed)?;
    writer
        .write_image_data(pixmap.data())
        .and_then(|()| writer.finish())
        .map_err(|_| DocumentIoError::ExportConversionFailed)?;
    Ok(encoded)
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

fn svg_options() -> Result<usvg::Options<'static>, DocumentIoError> {
    let release = !cfg!(debug_assertions)
        || std::env::var("OCTOPUS_FONT_PROFILE").as_deref() == Ok("release");
    svg_options_for_profile(release)
}

fn external_font_directory() -> Result<PathBuf, DocumentIoError> {
    if cfg!(debug_assertions) {
        return Ok(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../src/octopus/assets/fonts"));
    }
    let executable = std::env::current_exe()?;
    let directory = executable
        .parent()
        .ok_or(DocumentIoError::ExportConversionFailed)?;
    Ok(if cfg!(target_os = "linux") {
        directory.join("../lib/OctoPus/fonts")
    } else if cfg!(target_os = "macos") {
        directory.join("../Resources/lib/OctoPus/fonts")
    } else {
        directory.join("lib/OctoPus/fonts")
    })
}

fn svg_options_for_profile(release: bool) -> Result<usvg::Options<'static>, DocumentIoError> {
    svg_options_for_fonts(release, &external_font_directory()?)
}

fn svg_options_for_fonts(
    release: bool,
    root: &Path,
) -> Result<usvg::Options<'static>, DocumentIoError> {
    svg_options_for_policy(font_policy_for_target(release, std::env::consts::OS), root)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FontPolicy {
    Reference,
    LinuxRelease,
    SystemOnly,
}

fn font_policy_for_target(release: bool, target_os: &str) -> FontPolicy {
    if !release {
        FontPolicy::Reference
    } else if target_os == "linux" {
        FontPolicy::LinuxRelease
    } else {
        FontPolicy::SystemOnly
    }
}

fn svg_options_for_policy(
    policy: FontPolicy,
    root: &Path,
) -> Result<usvg::Options<'static>, DocumentIoError> {
    let mut font_database = usvg::fontdb::Database::new();
    if matches!(policy, FontPolicy::Reference | FontPolicy::LinuxRelease) {
        let manifest: serde_json::Value =
            serde_json::from_slice(&std::fs::read(root.join("manifest.json"))?)
                .map_err(|_| DocumentIoError::ExportConversionFailed)?;
        let faces = manifest["faces"]
            .as_array()
            .filter(|faces| faces.len() == 13)
            .ok_or(DocumentIoError::ExportConversionFailed)?;
        for face in faces {
            let name = face["file"]
                .as_str()
                .ok_or(DocumentIoError::ExportConversionFailed)?;
            let bytes = std::fs::read(root.join(name))?;
            let digest = format!("{:x}", Sha256::digest(&bytes));
            if face["sha256"].as_str() != Some(digest.as_str()) {
                return Err(DocumentIoError::ExportConversionFailed);
            }
            font_database.load_font_data(bytes);
        }
        font_database.set_sans_serif_family("Noto Sans SC");
        font_database.set_serif_family("Noto Serif SC");
    }
    if matches!(policy, FontPolicy::Reference | FontPolicy::SystemOnly) {
        font_database.load_system_fonts();
    }
    Ok(usvg::Options {
        font_family: match policy {
            FontPolicy::Reference => "Times New Roman",
            FontPolicy::LinuxRelease => "Noto Sans SC",
            FontPolicy::SystemOnly => "sans-serif",
        }
        .into(),
        fontdb: Arc::new(font_database),
        ..Default::default()
    })
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

fn encode_jpeg(
    pixmap: Pixmap,
    width: u32,
    height: u32,
    dpi: u16,
) -> Result<Vec<u8>, DocumentIoError> {
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
    let mut encoder = JpegEncoder::new_with_quality(&mut encoded, JPEG_QUALITY);
    encoder.set_pixel_density(PixelDensity::dpi(dpi));
    encoder
        .encode(&pixels, width, height, ExtendedColorType::Rgb8)
        .map_err(|_| DocumentIoError::ExportConversionFailed)?;
    Ok(encoded)
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use image::codecs::jpeg::JpegDecoder;
    use image::ImageDecoder;

    use super::{export_pdf, export_pdf_with_options, publish_raster_pages, ExportFormat};
    use crate::DocumentIoError;

    fn export_images(
        pages: &[String],
        dpi: u16,
        format: ExportFormat,
    ) -> Result<Vec<Vec<u8>>, DocumentIoError> {
        let directory = tempfile::tempdir().unwrap();
        let name = if format == ExportFormat::Png {
            "score.png"
        } else {
            "score.jpg"
        };
        let paths = publish_raster_pages(&directory.path().join(name), pages, &[], format, dpi)?;
        paths.iter().map(|path| Ok(std::fs::read(path)?)).collect()
    }

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
    fn score_a5_pdf_preserves_previous_page_size() {
        let svg = r#"<svg xmlns="http://www.w3.org/2000/svg" width="840" height="1193"><path d="M 10 10 L 100 100"/></svg>"#;
        let pages = vec![svg.to_owned()];
        let a5 = export_pdf_with_options(&pages, super::usvg::Options::default(), true).unwrap();
        let generic =
            export_pdf_with_options(&pages, super::usvg::Options::default(), false).unwrap();
        let a5_box = b"/MediaBox[0 0 531.75 750]";
        let generic_box = b"/MediaBox[0 0 630 894.75]";
        assert!(a5.windows(a5_box.len()).any(|item| item == a5_box));
        assert!(generic
            .windows(generic_box.len())
            .any(|item| item == generic_box));
        let huge = vec![svg.replace("width=\"840\"", "width=\"20000\"")];
        assert!(matches!(
            export_pdf_with_options(&huge, super::usvg::Options::default(), true),
            Err(DocumentIoError::ExportPageTooLarge)
        ));
    }

    fn bundled_font_directory() -> std::path::PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../src/octopus/assets/fonts")
    }

    #[test]
    fn external_fonts_fail_when_missing_or_corrupt() {
        let directory = tempfile::tempdir().unwrap();
        assert!(
            super::svg_options_for_policy(super::FontPolicy::LinuxRelease, directory.path())
                .is_err()
        );
        std::fs::write(directory.path().join("bad.ttf"), b"corrupt").unwrap();
        let face = serde_json::json!({"file": "bad.ttf", "sha256": "0".repeat(64)});
        let manifest = serde_json::json!({"faces": vec![face; 13]});
        std::fs::write(directory.path().join("manifest.json"), manifest.to_string()).unwrap();
        assert!(
            super::svg_options_for_policy(super::FontPolicy::LinuxRelease, directory.path())
                .is_err()
        );
    }

    #[test]
    fn release_font_policy_is_platform_specific() {
        use super::FontPolicy;

        assert_eq!(
            super::font_policy_for_target(false, "windows"),
            FontPolicy::Reference
        );
        assert_eq!(
            super::font_policy_for_target(true, "linux"),
            FontPolicy::LinuxRelease
        );
        assert_eq!(
            super::font_policy_for_target(true, "windows"),
            FontPolicy::SystemOnly
        );
        assert_eq!(
            super::font_policy_for_target(true, "macos"),
            FontPolicy::SystemOnly
        );
    }

    #[test]
    fn system_only_export_does_not_require_a_bundle_manifest() {
        let directory = tempfile::tempdir().unwrap();

        let options =
            super::svg_options_for_policy(super::FontPolicy::SystemOnly, directory.path())
                .expect("system-only export must not read a bundled manifest");

        assert_eq!(options.font_family, "sans-serif");
        let cjk_family = options
            .fontdb
            .faces()
            .flat_map(|face| face.families.iter().map(|family| family.0.as_str()))
            .find(|family| family.starts_with("Noto Sans CJK"));
        let family = cjk_family
            .or_else(|| {
                options
                    .fontdb
                    .faces()
                    .flat_map(|face| face.families.iter().map(|family| family.0.as_str()))
                    .find(|family| {
                        !family.is_empty()
                            && family.chars().all(|character| {
                                character.is_ascii_alphanumeric() || matches!(character, ' ' | '-')
                            })
                    })
            })
            .expect("the host supplies at least one system font");
        let text = if cjk_family.is_some() {
            "简谱中文"
        } else {
            "System font"
        };
        let svg = format!(
            r#"<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"><text x="10" y="40" font-family="{family}" font-size="16">{text}</text></svg>"#
        );
        let pdf = super::export_pdf_with_options(&[svg], options, false).unwrap();
        assert!(pdf
            .windows(b"/FontFile".len())
            .any(|item| item == b"/FontFile"));
        assert!(pdf
            .windows(b"/ToUnicode".len())
            .any(|item| item == b"/ToUnicode"));
    }

    #[test]
    fn release_database_includes_fallback_faces() {
        let options = super::svg_options_for_policy(
            super::FontPolicy::LinuxRelease,
            &bundled_font_directory(),
        )
        .unwrap();
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
        assert!(families.contains(&"MiSans"));
        assert!(families.contains(&"Zhuque Fangsong (technical preview)"));
        let svg = SVG_PAGE.replace("Microsoft YaHei", "Noto Sans SC");
        let pdf = super::export_pdf_with_options(&[svg], options, false).unwrap();
        assert!(pdf
            .windows(b"/ToUnicode".len())
            .any(|item| item == b"/ToUnicode"));
        assert!(pdf
            .windows(b"/FontFile".len())
            .any(|item| item == b"/FontFile"));
    }

    #[test]
    fn quoted_fangsong_family_embeds_the_selected_font() {
        let svg = SVG_PAGE.replace(
            "Microsoft YaHei",
            "&quot;Zhuque Fangsong (technical preview)&quot;",
        );
        let options = super::svg_options_for_policy(
            super::FontPolicy::LinuxRelease,
            &bundled_font_directory(),
        )
        .unwrap();
        let pdf = super::export_pdf_with_options(&[svg], options, false).unwrap();
        let name = b"ZhuqueFangsong-Regular";
        assert!(pdf.windows(name.len()).any(|item| item == name));
    }

    #[test]
    fn exports_multiple_vector_pdf_pages_with_embedded_text_resources() {
        let font_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../src/octopus/assets/fonts/MiSans-Regular.ttf");
        let mut font_database = super::usvg::fontdb::Database::new();
        font_database.load_font_file(font_path).unwrap();
        let options = super::usvg::Options {
            font_family: "MiSans".into(),
            fontdb: std::sync::Arc::new(font_database),
            ..Default::default()
        };
        let pages = vec![SVG_PAGE.replace("Microsoft YaHei", "MiSans"); 5];
        let pdf = export_pdf_with_options(&pages, options, false).unwrap();
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
    fn exports_jpg_at_300_dpi_with_white_background() {
        let images = export_images(&page(), 300, ExportFormat::Jpg).unwrap();
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

        assert_eq!((width, height), (313, 188));
        assert!(corner.iter().all(|channel| *channel >= 250));
        assert!(
            rightmost_ink > width * 3 / 4,
            "ink ends at x={rightmost_ink}"
        );
        assert!(
            bottommost_ink > height * 3 / 4,
            "ink ends at y={bottommost_ink}"
        );
        assert_eq!(&images[0][6..18], b"JFIF\0\x01\x02\x01\x01\x2c\x01\x2c");
    }

    #[test]
    fn exports_lossless_png_at_print_size() {
        let pages = export_images(&page(), 300, ExportFormat::Png).unwrap();
        let reader = png::Decoder::new(Cursor::new(&pages[0]))
            .read_info()
            .unwrap();
        let dims = reader.info().pixel_dims.unwrap();
        assert_eq!(
            (dims.xppu, dims.yppu, dims.unit),
            (11_811, 11_811, png::Unit::Meter)
        );
        let image = image::load_from_memory_with_format(&pages[0], image::ImageFormat::Png)
            .unwrap()
            .to_rgba8();
        assert_eq!(image.dimensions(), (313, 188));
        assert_eq!(image.get_pixel(0, 0).0, [255, 255, 255, 255]);
        assert!(image.pixels().any(|pixel| pixel.0 == [0, 0, 0, 255]));
        assert!(image.pixels().all(|pixel| pixel.0[3] == 255));
        assert!(matches!(
            export_images(&page(), 96, ExportFormat::Png),
            Err(DocumentIoError::InvalidExportDpi)
        ));
    }

    #[test]
    fn exports_fifteen_a4_pages_at_300_dpi_in_both_raster_formats() {
        let page = r#"<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1415"><rect x="20" y="20" width="20" height="20"/></svg>"#;
        let pages = vec![page.to_string(); 15];
        let directory = tempfile::tempdir().unwrap();
        for (extension, format) in [("png", ExportFormat::Png), ("jpg", ExportFormat::Jpg)] {
            let path = directory.path().join(format!("score.{extension}"));
            let outputs = publish_raster_pages(&path, &pages, &[], format, 300).unwrap();
            assert_eq!(outputs.len(), 15);
            let last = directory.path().join(format!("score_page_015.{extension}"));
            assert_eq!(outputs[14], last);
            assert_eq!(image::image_dimensions(last).unwrap(), (3125, 4422));
        }
    }

    #[test]
    fn failed_later_raster_page_preserves_the_existing_target() {
        let directory = tempfile::tempdir().unwrap();
        let selected = directory.path().join("score.png");
        let existing = directory.path().join("score_page_001.png");
        std::fs::write(&existing, b"original").unwrap();
        let pages = vec![SVG_PAGE.to_owned(), "not svg".to_owned()];
        assert!(publish_raster_pages(
            &selected,
            &pages,
            &crate::file_exports::existing_export_targets(&selected, ExportFormat::Png, 2).unwrap(),
            ExportFormat::Png,
            300
        )
        .is_err());
        assert_eq!(std::fs::read(existing).unwrap(), b"original");
        assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 1);
    }

    #[test]
    fn rejects_invalid_resolution_pages_and_resource_usage() {
        assert!(matches!(
            export_images(&page(), 150, ExportFormat::Jpg),
            Err(DocumentIoError::InvalidExportDpi)
        ));
        assert!(matches!(
            export_images(&["not svg".into()], 300, ExportFormat::Jpg),
            Err(DocumentIoError::InvalidExportPage)
        ));
        let filtered = r#"
            <svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">
                <filter id="f"/>
            </svg>
        "#;
        assert!(matches!(
            export_images(&[filtered.into()], 300, ExportFormat::Jpg),
            Err(DocumentIoError::UnsupportedExportFeature)
        ));
        let oversized = r#"<svg xmlns="http://www.w3.org/2000/svg" width="8000" height="6000"/>"#;
        assert!(matches!(
            export_images(&[oversized.into()], 300, ExportFormat::Jpg),
            Err(DocumentIoError::ExportPageTooLarge)
        ));
        assert!(matches!(export_pdf(&[]), Err(DocumentIoError::EmptyExport)));
    }
}
