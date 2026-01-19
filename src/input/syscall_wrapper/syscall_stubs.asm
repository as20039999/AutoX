.code

; SyscallInternal(rcx=cInputs, rdx=SSN, r8=pInputs, r9=cbSize)
; 系统调用约定:
; rax = SSN
; r10 = arg1 (from rcx)
; rdx = arg2 (from r8)
; r8  = arg3 (from r9)
SyscallInternal proc
    mov eax, edx      ; eax = SSN (2nd arg)
    mov r10, rcx      ; r10 = cInputs (1st arg)
    mov rdx, r8       ; rdx = pInputs (3rd arg -> 2nd syscall arg)
    mov r8, r9        ; r8 = cbSize (4th arg -> 3rd syscall arg)
    syscall
    ret
SyscallInternal endp

end
