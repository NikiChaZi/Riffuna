package riffuna.desktop

import com.sun.jna.*
import com.sun.jna.platform.win32.Shell32
import com.sun.jna.ptr.IntByReference
import java.awt.Window

object WindowsAppearance {
    private interface Dwm : Library {
        fun DwmSetWindowAttribute(
            hwnd: Pointer,
            attribute: Int,
            value: IntByReference,
            size: Int,
        ): Int
    }

    fun prepareIdentity() {
        if (System.getProperty("os.name").startsWith("Windows"))
            runCatching {
                Shell32.INSTANCE.SetCurrentProcessExplicitAppUserModelID(WString("Riffuna.Desktop"))
            }
    }

    fun apply(window: Window) {
        if (!System.getProperty("os.name").startsWith("Windows")) return
        runCatching {
            val api = Native.load("dwmapi", Dwm::class.java)
            val pointer = Native.getWindowPointer(window)
            api.DwmSetWindowAttribute(pointer, 20, IntByReference(1), 4)
            api.DwmSetWindowAttribute(pointer, 35, IntByReference(0x00141210), 4)
            api.DwmSetWindowAttribute(pointer, 36, IntByReference(0x00E8F1F4), 4)
        }
    }
}
