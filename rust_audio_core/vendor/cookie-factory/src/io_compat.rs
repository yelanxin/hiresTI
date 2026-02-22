// there's no real io error on a byte slice
pub type Error = ();
pub type Result<T> = core::result::Result<T, Error>;

pub trait Write {
    fn write(&mut self, buf: &[u8]) -> Result<usize>;
}

impl Write for &mut [u8] {
    fn write(&mut self, data: &[u8]) -> Result<usize> {
        let amt = core::cmp::min(data.len(), self.len());
        let (a, b) = core::mem::replace(self, &mut []).split_at_mut(amt);
        a.copy_from_slice(&data[..amt]);
        *self = b;
        Ok(amt)
    }
}

pub enum SeekFrom {
    Start(u64),
    Current(i64),
}

pub trait Seek {
    fn seek(&mut self, pos: SeekFrom) -> Result<u64>;
}

// Minimal re-implementation of std::io::Cursor so it
// also works in non-std environments
pub struct Cursor<T>(T, u64);

impl<'a> Cursor<&'a mut [u8]> {
    pub fn new(inner: &'a mut [u8]) -> Self {
        Self(inner, 0)
    }

    pub fn into_inner(self) -> &'a mut [u8] {
        self.0
    }

    pub fn position(&self) -> u64 {
        self.1 as u64
    }

    pub fn set_position(&mut self, pos: u64) {
        self.1 = pos;
    }

    pub fn get_mut(&mut self) -> &mut [u8] {
        self.0
    }

    pub fn get_ref(&self) -> &[u8] {
        self.0
    }
}

impl<'a> Write for Cursor<&'a mut [u8]> {
    fn write(&mut self, data: &[u8]) -> Result<usize> {
        let amt = (&mut self.0[(self.1 as usize)..]).write(data)?;
        self.1 += amt as u64;

        Ok(amt)
    }
}

impl<'a> Seek for Cursor<&'a mut [u8]> {
    fn seek(&mut self, pos: SeekFrom) -> Result<u64> {
        let (start, offset) = match pos {
            SeekFrom::Start(n) => {
                self.1 = n;
                return Ok(n);
            }
            SeekFrom::Current(n) => (self.1 as u64, n),
        };
        let new_pos = if offset >= 0 {
            start.checked_add(offset as u64)
        } else {
            start.checked_sub((offset.wrapping_neg()) as u64)
        };
        match new_pos {
            Some(n) => {
                self.1 = n;
                Ok(n)
            }
            None => panic!("invalid seek to a negative or overflowing position"),
        }
    }
}
