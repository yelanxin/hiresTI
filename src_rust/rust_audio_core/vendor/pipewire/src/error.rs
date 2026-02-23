// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

use thiserror::Error;
#[derive(Error, Debug)]
pub enum Error {
    #[error("Creation failed")]
    CreationFailed,
    #[error("No memory")]
    NoMemory,
    #[error("Wrong proxy type")]
    WrongProxyType,
    #[error(transparent)]
    SpaError(#[from] spa::utils::result::Error),
}
