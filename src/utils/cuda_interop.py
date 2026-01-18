
import ctypes
import torch
import os

# CUDA Constants
cudaSuccess = 0
cudaGraphicsRegisterFlagsNone = 0
cudaGraphicsMapFlagsNone = 0
cudaMemcpyDeviceToDevice = 3

class CUDAInterop:
    def __init__(self, texture_width, texture_height, region=None):
        self.texture_width = texture_width
        self.texture_height = texture_height
        
        # Region: (left, top, right, bottom) -> (x, y, w, h)
        if region:
            self.x = region[0]
            self.y = region[1]
            self.width = region[2] - region[0]
            self.height = region[3] - region[1]
        else:
            self.x = 0
            self.y = 0
            self.width = texture_width
            self.height = texture_height
            
        self.cudart = self._load_cudart()
        self.resource = ctypes.c_void_p(0)
        self.buffer_ptr = None
        self.registered = False
        
        # Setup signatures
        self.cudart.cudaGraphicsD3D11RegisterResource.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]
        self.cudart.cudaGraphicsD3D11RegisterResource.restype = ctypes.c_int
        
        self.cudart.cudaGraphicsMapResources.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        self.cudart.cudaGraphicsMapResources.restype = ctypes.c_int
        
        self.cudart.cudaGraphicsUnmapResources.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        self.cudart.cudaGraphicsUnmapResources.restype = ctypes.c_int
        
        self.cudart.cudaGraphicsSubResourceGetMappedArray.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        self.cudart.cudaGraphicsSubResourceGetMappedArray.restype = ctypes.c_int
        
        self.cudart.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        self.cudart.cudaMalloc.restype = ctypes.c_int
        
        self.cudart.cudaMemcpy2DFromArray.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t, # dst, dpitch
            ctypes.c_void_p, # src (cudaArray_t)
            ctypes.c_size_t, ctypes.c_size_t, # wOffset, hOffset
            ctypes.c_size_t, ctypes.c_size_t, # width, height
            ctypes.c_int # kind
        ]
        self.cudart.cudaMemcpy2DFromArray.restype = ctypes.c_int
        
        self._allocate_buffer()

    def _load_cudart(self):
        torch_lib = os.path.dirname(os.path.abspath(torch.__file__))
        # Try finding cudart64_*.dll
        import glob
        candidates = glob.glob(os.path.join(torch_lib, 'lib', 'cudart64_*.dll'))
        if not candidates:
            raise RuntimeError("Could not find cudart library in torch/lib")
        return ctypes.cdll.LoadLibrary(candidates[0])

    def _allocate_buffer(self):
        # Allocate CUDA buffer for BGRA image (4 channels, uint8)
        # Size is based on cropped region
        size = self.width * self.height * 4
        self.buffer_ptr = ctypes.c_void_p(0)
        ret = self.cudart.cudaMalloc(ctypes.byref(self.buffer_ptr), size)
        if ret != cudaSuccess:
            raise RuntimeError(f"cudaMalloc failed with error {ret}")

    def register_resource(self, d3d11_texture_ptr):
        if self.registered:
            return
        
        ret = self.cudart.cudaGraphicsD3D11RegisterResource(
            ctypes.byref(self.resource),
            ctypes.c_void_p(d3d11_texture_ptr),
            cudaGraphicsRegisterFlagsNone
        )
        if ret != cudaSuccess:
            raise RuntimeError(f"cudaGraphicsD3D11RegisterResource failed with error {ret}")
        self.registered = True

    def copy_to_buffer(self):
        if not self.registered:
            return None
            
        # Map
        ret = self.cudart.cudaGraphicsMapResources(1, ctypes.byref(self.resource), None)
        if ret != cudaSuccess:
            print(f"cudaGraphicsMapResources failed: {ret}")
            return None
            
        # Get Array
        cuda_array = ctypes.c_void_p(0)
        ret = self.cudart.cudaGraphicsSubResourceGetMappedArray(
            ctypes.byref(cuda_array),
            self.resource,
            0, 0
        )
        if ret != cudaSuccess:
            self.cudart.cudaGraphicsUnmapResources(1, ctypes.byref(self.resource), None)
            print(f"cudaGraphicsSubResourceGetMappedArray failed: {ret}")
            return None
            
        # Copy (Array to Linear Buffer)
        # width in bytes = width * 4 (BGRA)
        dst_pitch = self.width * 4
        width_bytes = self.width * 4
        
        # wOffset, hOffset are in elements? No, usually bytes for X?
        # cudaMemcpy2DFromArray:
        # srcX: The x-offset (in bytes) of the source array to start reading from.
        # srcY: The y-offset of the source array to start reading from.
        src_x_bytes = self.x * 4
        src_y = self.y
        
        ret = self.cudart.cudaMemcpy2DFromArray(
            self.buffer_ptr,
            dst_pitch,
            cuda_array,
            src_x_bytes, src_y, # wOffset, hOffset
            width_bytes,
            self.height,
            cudaMemcpyDeviceToDevice
        )
        
        # Unmap
        self.cudart.cudaGraphicsUnmapResources(1, ctypes.byref(self.resource), None)
        
        if ret != cudaSuccess:
            print(f"cudaMemcpy2DFromArray failed: {ret}")
            return None
            
        return self.buffer_ptr

    def get_tensor(self):
        ptr = self.copy_to_buffer()
        if ptr is None:
            return None
            
        # Create torch tensor from pointer
        # We use __cuda_array_interface__ protocol approach via a dummy object
        
        class CUDABuffer:
            def __init__(self, ptr, size, shape, typestr):
                self.__cuda_array_interface__ = {
                    "data": (ptr, False), # read-only=False
                    "shape": shape,
                    "typestr": typestr,
                    "version": 3
                }
        
        # BGRA uint8
        buffer_obj = CUDABuffer(
            ptr.value, 
            self.width * self.height * 4, 
            (self.height, self.width, 4), 
            "|u1"
        )
        
        # Create tensor (zero copy from buffer)
        tensor = torch.as_tensor(buffer_obj, device='cuda')
        
        # Convert BGRA to BGR and return
        # This is done on GPU
        return tensor[..., :3]
