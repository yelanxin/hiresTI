use std::{ffi::CString, fmt, mem::ManuallyDrop, ops::Deref, ptr};

/// A collection of key/value pairs.
///
/// # Examples
/// Create a `Properties` struct and access the stored values by key:
/// ```rust
/// use pipewire::{properties::{properties, Properties}};
///
/// let props = properties!{
///     "Key" => "Value",
///     "OtherKey" => "OtherValue"
/// };
///
/// assert_eq!(Some("Value"), props.get("Key"));
/// assert_eq!(Some("OtherValue"), props.get("OtherKey"));
/// ```
pub struct Properties {
    ptr: ptr::NonNull<pw_sys::pw_properties>,
}

/// A macro for creating a new `Properties` struct with predefined key-value pairs.
///
/// The macro accepts a list of `Key => Value` pairs, separated by commas.
///
/// # Examples:
/// Create a `Properties` struct from literals.
/// ```rust
/// use pipewire::properties::properties;
///
/// let props = properties!{
///    "Key1" => "Value1",
///    "Key2" => "Value2",
/// };
/// ```
///
/// Any expression that evaluates to a `impl Into<Vec<u8>>` can be used for both keys and values.
/// ```rust
/// use pipewire::prelude::*;
/// use pipewire::properties::properties;
///
/// let key = String::from("Key");
/// let value = vec![86, 97, 108, 117, 101]; // "Value" as an ASCII u8 vector.
/// let props = properties!{
///     key => value
/// };
///
/// assert_eq!(Some("Value"), props.get("Key"));
/// ```
#[macro_export]
macro_rules! __properties__ {
    {$($k:expr => $v:expr),+ $(,)?} => {{
        let mut properties = $crate::properties::Properties::new();
        $(
            properties.insert($k, $v);
        )*
        properties
    }};
}

pub use __properties__ as properties;

impl Properties {
    /// Create a new, initially empty `Properties` struct.
    pub fn new() -> Self {
        unsafe {
            let raw = std::ptr::NonNull::new(pw_sys::pw_properties_new(std::ptr::null()))
                .expect("Newly created pw_properties should not be null");

            Self::from_ptr(raw)
        }
    }

    /// Create a `Properties` struct from an existing raw `pw_properties` pointer.
    ///
    /// # Safety
    /// - The provided pointer must point to a valid, well-aligned `pw_properties` struct.
    /// - After this call, the generated `Properties` struct will assume ownership of the data pointed to,
    ///   so that data must not be freed elsewhere.
    pub unsafe fn from_ptr(ptr: ptr::NonNull<pw_sys::pw_properties>) -> Self {
        Self { ptr }
    }

    /// Consume the `Properties` struct, returning a pointer to the raw `pw_properties` struct.
    ///
    /// After this function, the caller is responsible for `pw_properties` struct,
    /// and should make sure it is freed when it is no longer needed.
    pub fn into_raw(self) -> *mut pw_sys::pw_properties {
        let this = ManuallyDrop::new(self);

        this.ptr.as_ptr()
    }

    // TODO: `fn from_string` that calls `pw_sys::pw_properties_new_string`
    // TODO: bindings for pw_properties_update_keys, pw_properties_update, pw_properties_add, pw_properties_add_keys

    /// Create a new `Properties` from a given dictionary.
    ///
    /// All the keys and values from `dict` are copied.
    pub fn from_dict(dict: &spa::utils::dict::DictRef) -> Self {
        let ptr = dict.as_raw();
        unsafe {
            let copy = pw_sys::pw_properties_new_dict(ptr);
            Self::from_ptr(ptr::NonNull::new(copy).expect("pw_properties_new_dict() returned NULL"))
        }
    }
}

impl AsRef<PropertiesRef> for Properties {
    fn as_ref(&self) -> &PropertiesRef {
        self.deref()
    }
}

impl AsRef<spa::utils::dict::DictRef> for Properties {
    fn as_ref(&self) -> &spa::utils::dict::DictRef {
        self.deref().as_ref()
    }
}

impl std::ops::Deref for Properties {
    type Target = PropertiesRef;

    fn deref(&self) -> &Self::Target {
        unsafe { self.ptr.cast().as_ref() }
    }
}

impl std::ops::DerefMut for Properties {
    fn deref_mut(&mut self) -> &mut Self::Target {
        unsafe { self.ptr.cast().as_mut() }
    }
}

impl Default for Properties {
    fn default() -> Self {
        Self::new()
    }
}

impl Clone for Properties {
    fn clone(&self) -> Self {
        unsafe {
            let ptr = pw_sys::pw_properties_copy(self.as_raw_ptr());
            let ptr = ptr::NonNull::new_unchecked(ptr);

            Self { ptr }
        }
    }
}

impl Drop for Properties {
    fn drop(&mut self) {
        unsafe { pw_sys::pw_properties_free(self.ptr.as_ptr()) }
    }
}

impl fmt::Debug for Properties {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let dict: &spa::utils::dict::DictRef = self.as_ref();
        // FIXME: Debug-print dict keys and values directly
        f.debug_tuple("Properties").field(dict).finish()
    }
}

#[repr(transparent)]
pub struct PropertiesRef(pw_sys::pw_properties);

impl PropertiesRef {
    pub fn as_raw(&self) -> &pw_sys::pw_properties {
        &self.0
    }

    /// Obtain a pointer to the underlying `pw_properties` struct.
    ///
    /// The pointer is only valid for the lifetime of the [`PropertiesRef`] struct the pointer was obtained from,
    /// and must not be dereferenced after it is dropped.
    ///
    /// Ownership of the `pw_properties` struct is not transferred to the caller and must not be manually freed.
    pub fn as_raw_ptr(&self) -> *mut pw_sys::pw_properties {
        std::ptr::addr_of!(self.0).cast_mut()
    }

    pub fn dict(&self) -> &spa::utils::dict::DictRef {
        unsafe { &*(&self.0.dict as *const spa_sys::spa_dict as *const spa::utils::dict::DictRef) }
    }

    // TODO: Impl as trait?
    pub fn to_owned(&self) -> Properties {
        unsafe {
            let ptr = pw_sys::pw_properties_copy(self.as_raw_ptr());
            Properties::from_ptr(ptr::NonNull::new_unchecked(ptr))
        }
    }

    pub fn get(&self, key: &str) -> Option<&str> {
        let key = CString::new(key).expect("key contains null byte");

        let res =
            unsafe { pw_sys::pw_properties_get(self.as_raw_ptr().cast_const(), key.as_ptr()) };

        let res = if !res.is_null() {
            unsafe { Some(std::ffi::CStr::from_ptr(res)) }
        } else {
            None
        };

        // FIXME: Don't return `None` if result is non-utf8
        res.and_then(|res| res.to_str().ok())
    }

    pub fn insert<K, V>(&mut self, key: K, value: V)
    where
        K: Into<Vec<u8>>,
        V: Into<Vec<u8>>,
    {
        let k = CString::new(key).unwrap();
        let v = CString::new(value).unwrap();
        unsafe { pw_sys::pw_properties_set(self.as_raw_ptr(), k.as_ptr(), v.as_ptr()) };
    }

    pub fn remove<T>(&mut self, key: T)
    where
        T: Into<Vec<u8>>,
    {
        let key = CString::new(key).unwrap();
        unsafe { pw_sys::pw_properties_set(self.as_raw_ptr(), key.as_ptr(), std::ptr::null()) };
    }

    pub fn clear(&mut self) {
        unsafe { pw_sys::pw_properties_clear(self.as_raw_ptr()) }
    }
}

impl AsRef<spa::utils::dict::DictRef> for PropertiesRef {
    fn as_ref(&self) -> &spa::utils::dict::DictRef {
        self.dict()
    }
}

impl fmt::Debug for PropertiesRef {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // FIXME: Debug-print dict key and values directly
        f.debug_tuple("PropertiesRef").field(self.as_ref()).finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new() {
        let props = properties! {
            "K0" => "V0"
        };

        let mut iter = props.dict().iter();
        assert_eq!(("K0", "V0"), iter.next().unwrap());
        assert_eq!(None, iter.next());
    }

    #[test]
    fn remove() {
        let mut props = properties! {
            "K0" => "V0"
        };

        assert_eq!(Some("V0"), props.dict().get("K0"));
        props.remove("K0");
        assert_eq!(None, props.dict().get("K0"));
    }

    #[test]
    fn insert() {
        let mut props = properties! {
            "K0" => "V0"
        };

        assert_eq!(None, props.dict().get("K1"));
        props.insert("K1", "V1");
        assert_eq!(Some("V1"), props.dict().get("K1"));
    }

    #[test]
    fn clone() {
        let props1 = properties! {
            "K0" => "V0"
        };
        let mut props2 = props1.clone();

        props2.insert("K1", "V1");

        // Now, props2 should contain ("K1", "V1"), but props1 should not.

        assert_eq!(None, props1.dict().get("K1"));
        assert_eq!(Some("V1"), props2.dict().get("K1"));
    }

    #[test]
    fn from_dict() {
        use spa::static_dict;

        let mut props = {
            let dict = static_dict! { "K0" => "V0" };

            Properties::from_dict(&dict)
        };

        assert_eq!(props.dict().len(), 1);
        assert_eq!(props.dict().get("K0"), Some("V0"));

        props.insert("K1", "V1");
        assert_eq!(props.dict().len(), 2);
        assert_eq!(props.dict().get("K1"), Some("V1"));
    }

    #[test]
    fn properties_ref() {
        let props = properties! {
            "K0" => "V0"
        };
        println!("{:?}", &props);
        let props_ref: &PropertiesRef = props.deref();

        assert_eq!(props_ref.dict().len(), 1);
        assert_eq!(props_ref.dict().get("K0"), Some("V0"));
        dbg!(&props_ref);

        let props_copy = props_ref.to_owned();
        assert_eq!(props_copy.dict().len(), 1);
        assert_eq!(props_copy.dict().get("K0"), Some("V0"));
    }
}
