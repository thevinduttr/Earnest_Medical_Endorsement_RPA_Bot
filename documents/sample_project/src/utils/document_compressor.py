"""
Document Compression Utility for CRM System
Compresses documents to below 5 MB before uploading to CRM system.
All processing is done locally to ensure data remains within the UAE region.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple
import tempfile
import shutil


# Maximum file size allowed by CRM system
MAX_FILE_SIZE_MB = 5
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024  # 5 MB in bytes


def get_file_size_mb(file_path: Path) -> float:
    """
    Get file size in megabytes
    
    Args:
        file_path: Path to the file
    
    Returns:
        File size in MB
    """
    if not file_path.exists():
        return 0.0
    return file_path.stat().st_size / (1024 * 1024)


def compress_image(
    input_path: Path, 
    output_path: Path, 
    target_size_mb: float = MAX_FILE_SIZE_MB,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Compress image files (JPEG, PNG, etc.) to target size
    Uses PIL/Pillow for local image compression
    
    Args:
        input_path: Path to input image
        output_path: Path to save compressed image
        target_size_mb: Target size in MB
        logger: Logger instance
    
    Returns:
        True if compression successful, False otherwise
    """
    try:
        from PIL import Image
        
        if logger:
            logger.info(f"Compressing image: {input_path.name} ({get_file_size_mb(input_path):.2f} MB)")
        
        # Open the image
        img = Image.open(input_path)
        
        # Convert RGBA to RGB if saving as JPEG
        if img.mode == 'RGBA' and output_path.suffix.lower() in ['.jpg', '.jpeg']:
            # Create white background for transparency
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[3] if len(img.split()) == 4 else None)
            img = rgb_img
        
        # Try progressively lower quality settings
        quality = 85
        max_attempts = 10
        
        for attempt in range(max_attempts):
            # Save with current quality
            save_params = {}
            
            if output_path.suffix.lower() in ['.jpg', '.jpeg']:
                save_params = {
                    'format': 'JPEG',
                    'quality': quality,
                    'optimize': True
                }
            elif output_path.suffix.lower() == '.png':
                save_params = {
                    'format': 'PNG',
                    'optimize': True,
                    'compress_level': 9
                }
            else:
                save_params = {'optimize': True}
            
            img.save(output_path, **save_params)
            
            # Check if size is acceptable
            current_size_mb = get_file_size_mb(output_path)
            if current_size_mb <= target_size_mb:
                if logger:
                    logger.info(f"Image compressed successfully: {output_path.name} ({current_size_mb:.2f} MB)")
                return True
            
            # If still too large, reduce quality more
            quality -= 10
            if quality < 20:
                # If quality is too low, try resizing the image
                if attempt == max_attempts - 1:
                    # Last attempt: resize image to 85% of original dimensions
                    new_width = int(img.width * 0.85)
                    new_height = int(img.height * 0.85)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    quality = 75  # Reset quality for resized image
                elif quality < 20:
                    quality = 20
        
        # If we couldn't compress enough, still return the best attempt
        final_size_mb = get_file_size_mb(output_path)
        if logger:
            logger.warning(f"Image compression completed but size is {final_size_mb:.2f} MB (target: {target_size_mb} MB)")
        
        return True
        
    except ImportError:
        if logger:
            logger.error("PIL/Pillow not installed. Cannot compress images. Install with: pip install Pillow")
        return False
    except Exception as e:
        if logger:
            logger.error(f"Error compressing image {input_path.name}: {e}")
        return False


def compress_pdf(
    input_path: Path,
    output_path: Path,
    target_size_mb: float = MAX_FILE_SIZE_MB,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Compress PDF files to target size
    Uses pypdf for local PDF compression and PIL for embedded image compression
    
    Args:
        input_path: Path to input PDF
        output_path: Path to save compressed PDF
        target_size_mb: Target size in MB
        logger: Logger instance
    
    Returns:
        True if compression successful, False otherwise
    """
    try:
        from pypdf import PdfReader, PdfWriter
        
        if logger:
            logger.info(f"Compressing PDF: {input_path.name} ({get_file_size_mb(input_path):.2f} MB)")
        
        # Read the PDF
        reader = PdfReader(input_path)
        writer = PdfWriter()
        
        # Copy all pages
        for page in reader.pages:
            writer.add_page(page)
        
        # Apply compression
        for page in writer.pages:
            page.compress_content_streams()
        
        # Write compressed PDF
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        
        compressed_size_mb = get_file_size_mb(output_path)
        original_size_mb = get_file_size_mb(input_path)
        
        # If compression didn't help much and file is still too large,
        # try converting PDF pages to compressed images
        if compressed_size_mb > target_size_mb and (original_size_mb - compressed_size_mb) < 0.5:
            if logger:
                logger.info(f"Basic PDF compression insufficient, attempting image-based compression...")
            
            # Try to compress PDF by converting pages to compressed images
            success = compress_pdf_with_images(input_path, output_path, target_size_mb, logger)
            if success:
                compressed_size_mb = get_file_size_mb(output_path)
        
        if logger:
            reduction = ((original_size_mb - compressed_size_mb) / original_size_mb) * 100 if original_size_mb > 0 else 0
            logger.info(f"PDF compressed: {output_path.name} ({compressed_size_mb:.2f} MB, {reduction:.1f}% reduction)")
        
        return True
        
    except ImportError:
        if logger:
            logger.error("pypdf not installed. Cannot compress PDFs. Install with: pip install pypdf")
        return False
    except Exception as e:
        if logger:
            logger.error(f"Error compressing PDF {input_path.name}: {e}")
        return False


def compress_pdf_with_images(
    input_path: Path,
    output_path: Path,
    target_size_mb: float = MAX_FILE_SIZE_MB,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Compress PDF by converting pages to compressed JPEG images
    This is more effective for PDFs containing scanned images
    
    Args:
        input_path: Path to input PDF
        output_path: Path to save compressed PDF
        target_size_mb: Target size in MB
        logger: Logger instance
    
    Returns:
        True if compression successful, False otherwise
    """
    try:
        import fitz  # PyMuPDF for better PDF image handling
        from PIL import Image
        import io
        
        if logger:
            logger.info(f"Converting PDF pages to compressed images: {input_path.name}")
        
        # Open input PDF with PyMuPDF
        input_doc = fitz.open(input_path)
        
        # Create output PDF document
        output_doc = fitz.open()
        
        # Convert each page to compressed image
        quality = 75  # Start with moderate quality
        zoom = 2.0  # 2x zoom for good quality
        
        for page_num in range(len(input_doc)):
            page = input_doc[page_num]
            
            # Render page to image
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to PIL Image for compression
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Compress as JPEG
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='JPEG', quality=quality, optimize=True)
            img_data = img_bytes.getvalue()
            
            # Create new page with compressed image
            img_rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
            new_page = output_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(img_rect, stream=img_data)
        
        # Save output PDF
        output_doc.save(output_path, garbage=4, deflate=True, clean=True)
        output_doc.close()
        input_doc.close()
        
        compressed_size_mb = get_file_size_mb(output_path)
        
        # If still too large, try with lower quality
        if compressed_size_mb > target_size_mb:
            if logger:
                logger.info(f"Still {compressed_size_mb:.2f} MB, retrying with lower quality...")
            
            # Retry with lower quality
            input_doc = fitz.open(input_path)
            output_doc = fitz.open()
            
            quality = 50  # Lower quality
            zoom = 1.5  # Lower resolution
            
            for page_num in range(len(input_doc)):
                page = input_doc[page_num]
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                img_bytes = io.BytesIO()
                img.save(img_bytes, format='JPEG', quality=quality, optimize=True)
                img_data = img_bytes.getvalue()
                
                img_rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
                new_page = output_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(img_rect, stream=img_data)
            
            output_doc.save(output_path, garbage=4, deflate=True, clean=True)
            output_doc.close()
            input_doc.close()
        
        return True
        
    except ImportError as e:
        if logger:
            logger.warning(f"PyMuPDF not available for advanced PDF compression: {e}")
            logger.info("Install with: pip install PyMuPDF")
        return False
    except Exception as e:
        if logger:
            logger.warning(f"Image-based PDF compression failed: {e}")
        return False


def compress_document(
    file_path: Path,
    logger: Optional[logging.Logger] = None,
    target_size_mb: float = MAX_FILE_SIZE_MB,
    temp_dir: Optional[Path] = None
) -> Tuple[Path, bool]:
    """
    Compress a document if it exceeds the target size
    All compression is done locally to ensure data remains within UAE region
    
    Args:
        file_path: Path to the document to compress
        logger: Logger instance for logging operations
        target_size_mb: Target maximum size in MB (default: 5 MB)
        temp_dir: Optional temporary directory for compressed files
    
    Returns:
        Tuple of (file_path, was_compressed)
        - file_path: Path to the file (original or compressed)
        - was_compressed: True if file was compressed, False if original returned
    """
    if not logger:
        logger = logging.getLogger(__name__)
    
    # Check if file exists
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return (file_path, False)
    
    # Get file size
    original_size_mb = get_file_size_mb(file_path)
    
    # If file is already below target size, return as-is
    if original_size_mb <= target_size_mb:
        logger.debug(f"File {file_path.name} is already below {target_size_mb} MB ({original_size_mb:.2f} MB), no compression needed")
        return (file_path, False)
    
    logger.info(f"File {file_path.name} exceeds {target_size_mb} MB ({original_size_mb:.2f} MB), attempting compression...")
    
    # Create temp directory for compressed file
    if temp_dir is None:
        temp_dir = Path(tempfile.gettempdir()) / "crm_compressed_docs"
    
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine output path
    compressed_path = temp_dir / f"compressed_{file_path.name}"
    
    # Get file extension
    file_ext = file_path.suffix.lower()
    
    # Compress based on file type
    compression_success = False
    
    # Image files
    if file_ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp']:
        compression_success = compress_image(file_path, compressed_path, target_size_mb, logger)
    
    # PDF files
    elif file_ext == '.pdf':
        compression_success = compress_pdf(file_path, compressed_path, target_size_mb, logger)
    
    # Other document types - cannot compress easily
    else:
        logger.warning(
            f"File type {file_ext} cannot be automatically compressed. "
            f"File {file_path.name} ({original_size_mb:.2f} MB) exceeds {target_size_mb} MB limit. "
            f"Manual compression required or upload may fail."
        )
        return (file_path, False)
    
    # Check if compression was successful and resulted in acceptable size
    if compression_success and compressed_path.exists():
        compressed_size_mb = get_file_size_mb(compressed_path)
        
        # If compressed file is acceptable size, return it
        if compressed_size_mb <= target_size_mb:
            logger.info(
                f"✓ Compression successful: {file_path.name} "
                f"({original_size_mb:.2f} MB → {compressed_size_mb:.2f} MB, "
                f"{((original_size_mb - compressed_size_mb) / original_size_mb * 100):.1f}% reduction)"
            )
            return (compressed_path, True)
        else:
            # Compression didn't reduce enough
            logger.warning(
                f"Compression reduced size but file still exceeds {target_size_mb} MB: "
                f"{file_path.name} ({original_size_mb:.2f} MB → {compressed_size_mb:.2f} MB). "
                f"Upload may fail."
            )
            # Return compressed version anyway as it's smaller
            return (compressed_path, True)
    
    # Compression failed, return original
    logger.warning(
        f"Compression failed for {file_path.name}. "
        f"File size ({original_size_mb:.2f} MB) exceeds {target_size_mb} MB limit. "
        f"Upload may fail."
    )
    return (file_path, False)


def cleanup_compressed_files(temp_dir: Optional[Path] = None, logger: Optional[logging.Logger] = None) -> None:
    """
    Clean up temporary compressed files
    
    Args:
        temp_dir: Temporary directory containing compressed files
        logger: Logger instance
    """
    if temp_dir is None:
        temp_dir = Path(tempfile.gettempdir()) / "crm_compressed_docs"
    
    if not temp_dir.exists():
        return
    
    try:
        shutil.rmtree(temp_dir)
        if logger:
            logger.debug(f"Cleaned up temporary compressed files from {temp_dir}")
    except Exception as e:
        if logger:
            logger.warning(f"Failed to cleanup temporary compressed files: {e}")


def get_compression_info(file_path: Path) -> dict:
    """
    Get compression information for a file
    
    Args:
        file_path: Path to the file
    
    Returns:
        Dictionary with file information
    """
    if not file_path.exists():
        return {
            "exists": False,
            "size_mb": 0.0,
            "needs_compression": False
        }
    
    size_mb = get_file_size_mb(file_path)
    file_ext = file_path.suffix.lower()
    
    compressible_extensions = [
        '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp',  # Images
        '.pdf'  # PDF
    ]
    
    return {
        "exists": True,
        "size_mb": size_mb,
        "needs_compression": size_mb > MAX_FILE_SIZE_MB,
        "can_compress": file_ext in compressible_extensions,
        "file_type": file_ext
    }
