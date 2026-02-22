// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

use bitflags::bitflags;
use std::fmt;

bitflags! {
    #[derive(Debug, PartialEq, Eq, Clone, Copy)]
    pub struct PermissionFlags: u32 {
        const R = pw_sys::PW_PERM_R;
        const W = pw_sys::PW_PERM_W;
        const X = pw_sys::PW_PERM_X;
        const M = pw_sys::PW_PERM_M;
        #[cfg(feature = "v0_3_77")]
        const L = pw_sys::PW_PERM_L;
    }
}

#[repr(transparent)]
pub struct Permission(pw_sys::pw_permission);

impl Permission {
    pub fn id(&self) -> u32 {
        self.0.id
    }

    pub fn permission_flags(&self) -> PermissionFlags {
        PermissionFlags::from_bits_retain(self.0.permissions)
    }
}

impl fmt::Debug for Permission {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Permission")
            .field("id", &self.id())
            .field("permission_flags", &self.permission_flags())
            .finish()
    }
}
