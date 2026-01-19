#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <windows.h>

typedef LONG NTSTATUS;

extern NTSTATUS SyscallInternal(UINT cInputs, DWORD ssn, LPINPUT pInputs, int cbSize);

// 全局 SSN，默认为 0，必须在使用前通过 set_ssn 设置
static DWORD g_ssn = 0;

static PyObject* method_set_ssn(PyObject* self, PyObject* args) {
    DWORD ssn;
    if (!PyArg_ParseTuple(args, "I", &ssn)) return NULL;
    g_ssn = ssn;
    Py_RETURN_NONE;
}

static PyObject* method_send_input(PyObject* self, PyObject* args) {
    PyObject* input_list;
    if (!PyArg_ParseTuple(args, "O", &input_list)) return NULL;
    if (!PyList_Check(input_list)) return NULL;

    if (g_ssn == 0) {
        PyErr_SetString(PyExc_RuntimeError, "Syscall SSN not set. Call set_ssn() first.");
        return NULL;
    }

    Py_ssize_t n = PyList_Size(input_list);
    if (n == 0) return PyLong_FromLong(0);

    INPUT* inputs = (INPUT*)malloc(sizeof(INPUT) * n);
    if (!inputs) return PyErr_NoMemory();
    memset(inputs, 0, sizeof(INPUT) * n);

    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject* item = PyList_GetItem(input_list, i);
        if (!PyDict_Check(item)) continue;

        PyObject* pType = PyDict_GetItemString(item, "type");
        if (pType) inputs[i].type = (DWORD)PyLong_AsLong(pType);

        if (inputs[i].type == INPUT_MOUSE) {
            PyObject* pDx = PyDict_GetItemString(item, "dx");
            PyObject* pDy = PyDict_GetItemString(item, "dy");
            PyObject* pFlags = PyDict_GetItemString(item, "flags");
            PyObject* pData = PyDict_GetItemString(item, "data");
            
            if (pDx) inputs[i].mi.dx = (LONG)PyLong_AsLong(pDx);
            if (pDy) inputs[i].mi.dy = (LONG)PyLong_AsLong(pDy);
            if (pFlags) inputs[i].mi.dwFlags = (DWORD)PyLong_AsLong(pFlags);
            if (pData) inputs[i].mi.mouseData = (DWORD)PyLong_AsLong(pData);
        } 
        else if (inputs[i].type == INPUT_KEYBOARD) {
            PyObject* pVk = PyDict_GetItemString(item, "vk");
            PyObject* pFlags = PyDict_GetItemString(item, "flags");
            
            if (pVk) inputs[i].ki.wVk = (WORD)PyLong_AsLong(pVk);
            if (pFlags) inputs[i].ki.dwFlags = (DWORD)PyLong_AsLong(pFlags);
        }
    }

    NTSTATUS status = SyscallInternal((UINT)n, g_ssn, inputs, (int)sizeof(INPUT));

    free(inputs);
    return PyLong_FromLong((long)status);
}

static PyMethodDef SyscallMethods[] = {
    {"send_input", method_send_input, METH_VARARGS, "Execute NtUserSendInput via direct syscall"},
    {"set_ssn", method_set_ssn, METH_VARARGS, "Set the system call number for NtUserSendInput"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef syscall_module = {
    PyModuleDef_HEAD_INIT, "syscall_input_lib", NULL, -1, SyscallMethods
};

PyMODINIT_FUNC PyInit_syscall_input_lib(void) {
    return PyModule_Create(&syscall_module);
}
