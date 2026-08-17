import subprocess
import tempfile
import os
import base64
from PIL import Image
import io
from typing import Optional, Dict
from app.config.settings import settings
from app.core.logging import logger
from app.utils.image_utils import ImageUtils
from app.utils.system_utils import SystemUtils

class ScreenshotService:
    """Service for screenshot capture with dynamic UDID support"""
    
    def __init__(self, udid: Optional[str] = None):
        self.udid = udid
    
    def set_udid(self, udid: str):
        """Set the UDID for this service instance"""
        self.udid = udid
    
    def capture_screenshot(self, quality: int = None) -> Optional[Dict[str, any]]:
        """Capture device screenshot"""
        if not self.udid:
            logger.error("No UDID set for screenshot capture")
            return None
            
        if quality is None:
            quality = settings.DEFAULT_JPEG_QUALITY
            
        temp_path = None
        try:
            temp_file = SystemUtils.create_temp_file('.png')
            temp_path = temp_file.name
            temp_file.close()  # Close the descriptor so other processes can write to the path
            
            # Try xcrun simctl first as it is built-in and more reliable (no idb daemon needed)
            cmd = ["xcrun", "simctl", "io", self.udid, "screenshot", temp_path]
            result = subprocess.run(
                cmd, capture_output=True, 
                timeout=settings.SCREENSHOT_TIMEOUT
            )
            
            # If simctl fails, try idb as fallback
            if result.returncode != 0 or not os.path.exists(temp_path):
                simctl_err = result.stderr.decode('utf-8', errors='ignore') if result.stderr else "File not created"
                logger.warning(f"simctl screenshot failed, trying idb fallback. Simctl error: {simctl_err}")
                
                cmd = ["idb", "screenshot", "--udid", self.udid, temp_path]
                result = subprocess.run(
                    cmd, capture_output=True, 
                    timeout=settings.SCREENSHOT_TIMEOUT
                )
            
            if result.returncode == 0 and os.path.exists(temp_path):
                with Image.open(temp_path) as img:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Convert to JPEG
                    output = io.BytesIO()
                    img.save(output, format='JPEG', quality=quality, optimize=True)
                    image_data = output.getvalue()
                
                return {
                    "data": base64.b64encode(image_data).decode('utf-8'),
                    "pixel_width": img.width,
                    "pixel_height": img.height
                }
            else:
                stderr_output = result.stderr.decode('utf-8', errors='ignore') if result.stderr else "Unknown error"
                logger.error(f"Failed to capture screenshot. Return code: {result.returncode}, Error: {stderr_output}")
                
        except subprocess.TimeoutExpired:
            logger.error(f"Screenshot timeout for UDID: {self.udid}")
        except Exception as e:
            logger.error(f"Screenshot error for UDID {self.udid}: {e}")
        finally:
            if temp_path:
                SystemUtils.cleanup_temp_file(temp_path)
        
        return None
    
    def capture_ultra_fast_screenshot(self) -> Optional[Dict[str, any]]:
        """Ultra-fast screenshot for real-time streaming"""
        return self.capture_screenshot(quality=settings.DEFAULT_JPEG_QUALITY)
    
    def capture_high_quality_screenshot(self) -> Optional[Dict[str, any]]:
        """High-quality screenshot"""
        return self.capture_screenshot(quality=settings.WEBRTC_HIGH_QUALITY)