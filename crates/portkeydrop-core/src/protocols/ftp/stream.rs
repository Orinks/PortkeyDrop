//! A socket that may or may not be wrapped in TLS.
//!
//! FTPS upgrades an existing plaintext connection in place, so both the control
//! and data channels need a handle that can be either form. Keeping that in one
//! enum lets the rest of the client ignore the distinction.

use std::io::{Read, Write};
use std::net::TcpStream;

use native_tls::TlsStream;

/// Either a plain TCP socket or a TLS session over one.
pub enum Stream {
    Plain(TcpStream),
    Tls(Box<TlsStream<TcpStream>>),
}

impl Stream {
    /// Whether this stream is encrypted.
    #[allow(dead_code)] // Used by diagnostics and tests.
    pub fn is_encrypted(&self) -> bool {
        matches!(self, Stream::Tls(_))
    }

    /// Borrow the underlying socket, for timeouts and shutdown.
    pub fn socket(&self) -> &TcpStream {
        match self {
            Stream::Plain(socket) => socket,
            Stream::Tls(session) => session.get_ref(),
        }
    }

    /// Close the write half so the peer sees end-of-file.
    ///
    /// FTP signals the end of an upload by closing the data connection, so this
    /// is what tells the server the transfer is complete.
    pub fn shutdown_write(&mut self) -> std::io::Result<()> {
        match self {
            Stream::Plain(socket) => socket.shutdown(std::net::Shutdown::Write),
            // A TLS session must send close_notify before the socket closes,
            // otherwise strict servers treat the transfer as truncated.
            Stream::Tls(session) => {
                let _ = session.shutdown();
                Ok(())
            }
        }
    }
}

impl Read for Stream {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        match self {
            Stream::Plain(socket) => socket.read(buf),
            Stream::Tls(session) => session.read(buf),
        }
    }
}

impl Write for Stream {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        match self {
            Stream::Plain(socket) => socket.write(buf),
            Stream::Tls(session) => session.write(buf),
        }
    }

    fn flush(&mut self) -> std::io::Result<()> {
        match self {
            Stream::Plain(socket) => socket.flush(),
            Stream::Tls(session) => session.flush(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::BufRead;
    use std::net::TcpListener;

    /// A loopback pair: a server that echoes one line, and a client stream.
    fn loopback_pair() -> (std::thread::JoinHandle<String>, Stream) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (socket, _) = listener.accept().unwrap();
            let mut reader = std::io::BufReader::new(socket);
            let mut line = String::new();
            reader.read_line(&mut line).unwrap();
            line
        });
        let client = Stream::Plain(TcpStream::connect(address).unwrap());
        (server, client)
    }

    #[test]
    fn a_plain_stream_reports_itself_as_unencrypted() {
        let (server, client) = loopback_pair();
        assert!(!client.is_encrypted());
        drop(client);
        let _ = server.join();
    }

    #[test]
    fn writes_reach_the_peer() {
        let (server, mut client) = loopback_pair();
        client.write_all(b"HELLO\r\n").unwrap();
        client.flush().unwrap();
        assert_eq!(server.join().unwrap(), "HELLO\r\n");
    }

    #[test]
    fn the_socket_is_reachable_for_timeout_configuration() {
        let (server, client) = loopback_pair();
        client
            .socket()
            .set_read_timeout(Some(std::time::Duration::from_secs(1)))
            .unwrap();
        drop(client);
        let _ = server.join();
    }
}
