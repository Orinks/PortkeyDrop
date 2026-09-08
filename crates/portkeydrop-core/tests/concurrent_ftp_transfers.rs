//! Real protocol + scheduler regressions without a GUI or remote account.
use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

use portkeydrop_core::protocols::{create_client, ConnectionInfo, Protocol};
use portkeydrop_core::transfer::{SharedClient, Status, TransferService};

fn wait_for(service: &TransferService, id: &str, expected: Status) {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let job = service.job(id).unwrap();
        if job.status == expected {
            return;
        }
        assert!(
            !job.status.is_finished(),
            "unexpected outcome: {:?}: {:?}",
            job.status,
            job.error
        );
        assert!(Instant::now() < deadline, "job never reached {expected:?}");
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn two_folder_downloads(cancel_second: bool) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = listener.local_addr().unwrap();
    let (scanning, scan_started) = mpsc::channel();
    let (release, released) = mpsc::channel();
    let payload: Vec<u8> = (0..131_072).map(|n| (n % 251) as u8).collect();
    let server_payload = payload.clone();
    let server = std::thread::spawn(move || {
        let (stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(8)))
            .unwrap();
        stream
            .set_write_timeout(Some(Duration::from_secs(8)))
            .unwrap();
        let mut control = BufReader::new(stream);
        control.get_mut().write_all(b"220 test server\r\n").unwrap();
        let mut passive = None;
        loop {
            let mut line = String::new();
            if control.read_line(&mut line).unwrap_or(0) == 0 {
                break;
            }
            let command = line.trim_end();
            let reply = if command.starts_with("USER ") {
                "230 logged in\r\n".to_string()
            } else if command == "TYPE I" {
                "200 binary\r\n".to_string()
            } else if command == "PWD" {
                "257 \"/\"\r\n".to_string()
            } else if command == "EPSV" {
                let data = TcpListener::bind("127.0.0.1:0").unwrap();
                let reply = format!(
                    "229 passive (|||{}|)\r\n",
                    data.local_addr().unwrap().port()
                );
                passive = Some(data);
                reply
            } else if command.starts_with("SIZE ") {
                format!("213 {}\r\n", server_payload.len())
            } else if command.starts_with("MLSD ") || command.starts_with("RETR ") {
                if command == "MLSD /first" {
                    scanning.send(()).unwrap();
                    released
                        .recv_timeout(Duration::from_secs(5))
                        .expect("test must release the stalled scan");
                }
                control
                    .get_mut()
                    .write_all(b"150 data follows\r\n")
                    .unwrap();
                let (mut data, _) = passive.take().unwrap().accept().unwrap();
                data.set_write_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                if command.starts_with("MLSD ") {
                    write!(
                        data,
                        "type=file;size={}; payload.bin\r\n",
                        server_payload.len()
                    )
                    .unwrap();
                } else {
                    data.write_all(&server_payload).unwrap();
                }
                drop(data);
                "226 complete\r\n".to_string()
            } else if command == "QUIT" {
                let _ = control.get_mut().write_all(b"221 goodbye\r\n");
                break;
            } else {
                panic!("unexpected FTP command: {command}");
            };
            control.get_mut().write_all(reply.as_bytes()).unwrap();
        }
    });
    let mut ftp = create_client(
        ConnectionInfo {
            protocol: Protocol::Ftp,
            host: endpoint.ip().to_string(),
            port: endpoint.port(),
            timeout: 8,
            ..Default::default()
        },
        None,
        None,
    )
    .unwrap();
    ftp.connect().unwrap();
    let client: SharedClient = Arc::new(Mutex::new(ftp));
    let service = TransferService::new(2);
    let dir = tempfile::tempdir().unwrap();
    let first = service.submit_download(
        Arc::clone(&client),
        "/first",
        &dir.path().join("first").to_string_lossy(),
        0,
        true,
        false,
    );
    scan_started.recv_timeout(Duration::from_secs(5)).unwrap();
    let (submitted, received) = mpsc::channel();
    let submit_service = Arc::clone(&service);
    let submit_client = Arc::clone(&client);
    let second_path = dir.path().join("second");
    let submitter = std::thread::spawn(move || {
        let id = submit_service.submit_download(
            submit_client,
            "/second",
            &second_path.to_string_lossy(),
            0,
            true,
            false,
        );
        submitted.send(id).unwrap();
    });
    let result = received.recv_timeout(Duration::from_secs(1));
    if result.is_err() {
        let _ = release.send(());
    }
    let second = result.expect("second folder blocked while the first was scanning over FTP");
    submitter.join().unwrap();
    if cancel_second {
        wait_for(&service, &second, Status::InProgress);
        service.cancel(&second);
        // The first folder still holds the real FTP session here.
        wait_for(&service, &second, Status::Cancelled);
    }
    release.send(()).unwrap();
    wait_for(&service, &first, Status::Complete);
    assert_eq!(
        std::fs::read(dir.path().join("first/payload.bin")).unwrap(),
        payload
    );
    if cancel_second {
        assert!(!dir.path().join("second").exists());
    } else {
        wait_for(&service, &second, Status::Complete);
        assert_eq!(
            std::fs::read(dir.path().join("second/payload.bin")).unwrap(),
            payload
        );
    }
    client.lock().unwrap().disconnect();
    drop(service);
    server.join().unwrap();
}

#[test]
fn real_ftp_two_folders_complete_with_exact_file_contents() {
    two_folder_downloads(false);
}

#[test]
fn real_ftp_second_folder_cancels_while_first_is_stalled() {
    two_folder_downloads(true);
}
