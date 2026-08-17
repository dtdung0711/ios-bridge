import subprocess
import re
from typing import Tuple, Optional
from app.config.settings import settings
from app.core.logging import logger
from app.core.exceptions import DeviceNotAccessibleException

class DeviceService:
    """Service for device interactions"""
    
    def __init__(self, udid: Optional[str] = None):
        self.udid = udid
        self._point_dimensions_cache: Optional[Tuple[int, int]] = None
    
    def set_udid(self, udid: str):
        """Set the UDID for this service instance"""
        self.udid = udid
        self._point_dimensions_cache = None  # Reset cache when UDID changes

    def _ensure_idb_companion_running(self):
        """Ensure idb-companion is running for this device"""
        if not self.udid:
            return
            
        try:
            import psutil
            import time
            import os
            
            companion_running = False
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline') or []
                    cmdline_str = " ".join(cmdline).lower()
                    if "idb-companion" in cmdline_str and self.udid.lower() in cmdline_str:
                        companion_running = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            if not companion_running:
                # Deep scan Homebrew folders for idb-companion on macOS
                idb_companion_bin = "idb-companion"  # default fallback
                found_paths = []
                
                # Check basic paths first
                home_dir = os.path.expanduser("~")
                search_dirs = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/tmp", os.path.join(home_dir, "idb-bin")]
                for d in search_dirs:
                    for bin_name in ["idb-companion", "idb_companion"]:
                        p = os.path.join(d, bin_name)
                        if os.path.exists(p):
                            found_paths.append(p)
                        
                # Dynamic scan for Homebrew prefix and Cellar folders up to 4 levels deep
                for base_dir in ["/opt/homebrew", "/usr/local"]:
                    if os.path.exists(base_dir):
                        try:
                            for root, dirs, files in os.walk(base_dir):
                                # Limit scan depth to keep it extremely fast
                                depth = root.count(os.sep) - base_dir.count(os.sep)
                                if depth > 4:
                                    del dirs[:]  # Don't recurse deeper
                                    continue
                                if "idb-companion" in files:
                                    p = os.path.join(root, "idb-companion")
                                    if p not in found_paths:
                                        found_paths.append(p)
                        except Exception:
                            pass
                
                logger.info(f"🔍 Found idb-companion candidates: {found_paths}")
                
                # Select the first executable path
                for path in found_paths:
                    if os.access(path, os.X_OK):
                        idb_companion_bin = path
                        break
                
                cmd = [idb_companion_bin, "--udid", self.udid]
                logger.info(f"idb-companion not running for {self.udid}. Spawning: {' '.join(cmd)}")
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                # Wait for socket to bind
                time.sleep(1.5)
        except Exception as e:
            logger.error(f"Error ensuring idb-companion is running: {e}")
    
    async def get_point_dimensions(self) -> Tuple[int, int]:
        """Get device point dimensions with caching"""
        if not self.udid:
            raise DeviceNotAccessibleException("No UDID set for device service")
            
        if self._point_dimensions_cache:
            return self._point_dimensions_cache
        
        try:
            self._ensure_idb_companion_running()
            cmd = ["idb", "describe", "--udid", self.udid]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            
            if result.returncode == 0:
                width_match = re.search(r'width_points=(\d+)', result.stdout)
                height_match = re.search(r'height_points=(\d+)', result.stdout)
                
                if width_match and height_match:
                    self._point_dimensions_cache = (
                        int(width_match.group(1)), 
                        int(height_match.group(1))
                    )
                    return self._point_dimensions_cache
        except Exception as e:
            logger.error(f"Error getting point dimensions: {e}")
        
        # Default dimensions
        self._point_dimensions_cache = (390, 844)
        return self._point_dimensions_cache
    
    async def _native_tap(self, x: int, y: int) -> bool:
        """Native macOS cliclick tap fallback"""
        try:
            from app.utils.system_utils import SystemUtils
            window_info = SystemUtils.get_simulator_window_info()
            point_w, point_h = await self.get_point_dimensions()
            
            click_x = window_info["x"] + int((x / point_w) * window_info["width"])
            click_y = window_info["y"] + int((y / point_h) * window_info["height"])
            
            cmd = ["cliclick", f"c:{click_x},{click_y}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                logger.info(f"✅ Native cliclick tap at ({click_x}, {click_y})")
                return True
        except Exception as e:
            logger.error(f"Native tap failed: {e}")
        return False

    async def _native_swipe(self, start_x: int, start_y: int, end_x: int, end_y: int) -> bool:
        """Native macOS cliclick drag/swipe fallback"""
        try:
            from app.utils.system_utils import SystemUtils
            window_info = SystemUtils.get_simulator_window_info()
            point_w, point_h = await self.get_point_dimensions()
            
            s_x = window_info["x"] + int((start_x / point_w) * window_info["width"])
            s_y = window_info["y"] + int((start_y / point_h) * window_info["height"])
            e_x = window_info["x"] + int((end_x / point_w) * window_info["width"])
            e_y = window_info["y"] + int((end_y / point_h) * window_info["height"])
            
            cmd = ["cliclick", f"dd:{s_x},{s_y}", f"du:{e_x},{e_y}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                logger.info(f"✅ Native cliclick swipe ({s_x},{s_y}) -> ({e_x},{e_y})")
                return True
        except Exception as e:
            logger.error(f"Native swipe failed: {e}")
        return False

    async def _native_button(self, button: str) -> bool:
        """Native macOS AppleScript hardware buttons fallback"""
        try:
            btn = button.lower()
            if btn == 'home':
                script = 'tell application "Simulator" to activate\ntell application "System Events" to key code 4 using {command down, shift down}'
            elif btn == 'lock':
                script = 'tell application "Simulator" to activate\ntell application "System Events" to key code 37 using {command down}'
            elif btn == 'siri':
                script = 'tell application "Simulator" to activate\ntell application "System Events" to key code 1 using {command down, shift down}'
            else:
                return False
                
            res = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2)
            return res.returncode == 0
        except Exception:
            return False

    async def _native_text(self, text: str) -> bool:
        """Native macOS text input fallback"""
        try:
            res = subprocess.run(["cliclick", f"t:{text}"], capture_output=True, timeout=3)
            return res.returncode == 0
        except Exception:
            return False

    async def tap(self, x: int, y: int) -> bool:
        """Perform tap gesture"""
        if not self.udid:
            logger.error("No UDID set for tap action")
            return False
            
        try:
            self._ensure_idb_companion_running()
            cmd = ["idb", "ui", "tap", str(x), str(y), "--udid", self.udid]
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   timeout=settings.TAP_TIMEOUT)
            
            if result.returncode == 0:
                logger.info(f"✅ Tap: ({x}, {y}) on {self.udid}")
                return True
            else:
                logger.warning(f"idb tap failed ({result.stderr}), using native cliclick fallback...")
                return await self._native_tap(x, y)
        except Exception as e:
            logger.warning(f"idb tap error: {e}, using native cliclick fallback...")
            return await self._native_tap(x, y)
    
    async def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, 
                   duration: float = 0.2) -> bool:
        """Perform swipe gesture"""
        if not self.udid:
            logger.error("No UDID set for swipe action")
            return False
            
        try:
            self._ensure_idb_companion_running()
            cmd = [
                "idb", "ui", "swipe", 
                str(start_x), str(start_y), str(end_x), str(end_y),
                "--duration", str(duration), "--udid", self.udid
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   timeout=settings.SWIPE_TIMEOUT)
            
            if result.returncode == 0:
                logger.info(f"✅ Swipe: ({start_x}, {start_y}) -> ({end_x}, {end_y}) on {self.udid}")
                return True
            else:
                logger.warning("idb swipe failed, using native cliclick fallback...")
                return await self._native_swipe(start_x, start_y, end_x, end_y)
        except Exception as e:
            logger.warning(f"idb swipe error: {e}, using native cliclick fallback...")
            return await self._native_swipe(start_x, start_y, end_x, end_y)
    
    async def input_text(self, text: str) -> bool:
        """Input text"""
        if not self.udid:
            logger.error("No UDID set for text input")
            return False
            
        try:
            self._ensure_idb_companion_running()
            cmd = ["idb", "ui", "text", text, "--udid", self.udid]
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   timeout=settings.TEXT_TIMEOUT)
            
            if result.returncode == 0:
                logger.info("✅ Text entered")
                return True
            else:
                return await self._native_text(text)
        except Exception as e:
            return await self._native_text(text)
    
    async def input_key(self, key: str, duration: float = None) -> bool:
        """Input individual key"""
        if not self.udid:
            logger.error("No UDID set for key input")
            return False
            
        try:
            self._ensure_idb_companion_running()
            cmd = ["idb", "ui", "key", key, "--udid", self.udid]
            if duration is not None:
                cmd.extend(["--duration", str(duration)])
                
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   timeout=settings.TEXT_TIMEOUT)
            
            if result.returncode == 0:
                logger.info(f"✅ Key entered: {key}")
                return True
            else:
                logger.error(f"❌ Key failed: {key} - {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Key input error: {e}")
            return False
    
    async def press_button(self, button: str) -> bool:
        """Press device button"""
        if not self.udid:
            logger.error("No UDID set for button press")
            return False
            
        try:
            self._ensure_idb_companion_running()
            button_mapping = {
                'home': 'HOME', 'lock': 'LOCK', 'siri': 'SIRI',
                'side-button': 'SIDE_BUTTON', 'apple-pay': 'APPLE_PAY'
            }
            idb_button = button_mapping.get(button, button.upper())
            
            cmd = ["idb", "ui", "button", idb_button, "--udid", self.udid]
            result = subprocess.run(cmd, capture_output=True, text=True, 
                                   timeout=settings.TAP_TIMEOUT)
            
            if result.returncode == 0:
                logger.info(f"✅ Button: {button} on {self.udid}")
                return True
            else:
                return await self._native_button(button)
        except Exception as e:
            return await self._native_button(button)
    
    async def is_accessible(self) -> bool:
        """Check if device is accessible"""
        if not self.udid:
            return False
            
        try:
            cmd = ["idb", "list-targets"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return self.udid in result.stdout
        except Exception:
            return False