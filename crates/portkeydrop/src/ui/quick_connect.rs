//! The quick connect bar.
//!
//! Every field is preceded by its own label and given a matching accessible
//! name, so tabbing along the bar announces "Host", "Port", "Username" rather
//! than "edit, edit, edit".

use wxdragon::prelude::*;

use portkeydrop_core::protocols::{Protocol, SUPPORTED_PROTOCOL_VALUES};

use super::main_frame::QuickConnectBar;
use super::state::AppState;

impl QuickConnectBar {
    /// Build the bar under `parent`.
    pub(super) fn build(parent: &Panel, state: &AppState) -> Self {
        let panel = Panel::builder(parent).build();
        let sizer = BoxSizer::builder(Orientation::Horizontal).build();

        let add_label = |text: &str| {
            let label = StaticText::builder(&panel).with_label(text).build();
            sizer.add(
                &label,
                0,
                SizerFlag::AlignCenterVertical | SizerFlag::Left,
                6,
            );
        };

        add_label("&Protocol:");
        let protocol = Choice::builder(&panel).build();
        for name in SUPPORTED_PROTOCOL_VALUES {
            protocol.append(name);
        }
        protocol.set_name("Protocol");
        let default_protocol: Protocol = state
            .settings
            .connection
            .protocol
            .parse()
            .unwrap_or(Protocol::Sftp);
        let selected = SUPPORTED_PROTOCOL_VALUES
            .iter()
            .position(|name| *name == default_protocol.as_str())
            .unwrap_or(0);
        protocol.set_selection(selected as u32);
        sizer.add(
            &protocol,
            0,
            SizerFlag::AlignCenterVertical | SizerFlag::All,
            2,
        );

        add_label("&Host:");
        let host = TextCtrl::builder(&panel)
            .with_size(Size::new(180, -1))
            .with_style(TextCtrlStyle::ProcessEnter)
            .build();
        host.set_name("Host");
        sizer.add(&host, 1, SizerFlag::AlignCenterVertical | SizerFlag::All, 2);

        add_label("P&ort:");
        let port = TextCtrl::builder(&panel)
            .with_size(Size::new(64, -1))
            .with_style(TextCtrlStyle::ProcessEnter)
            .build();
        port.set_name("Port");
        port.set_value(&default_protocol.default_port(false).to_string());
        sizer.add(&port, 0, SizerFlag::AlignCenterVertical | SizerFlag::All, 2);

        add_label("&Username:");
        let username = TextCtrl::builder(&panel)
            .with_size(Size::new(120, -1))
            .with_style(TextCtrlStyle::ProcessEnter)
            .build();
        username.set_name("Username");
        sizer.add(
            &username,
            0,
            SizerFlag::AlignCenterVertical | SizerFlag::All,
            2,
        );

        add_label("Pass&word:");
        let password = TextCtrl::builder(&panel)
            .with_size(Size::new(120, -1))
            .with_style(TextCtrlStyle::Password | TextCtrlStyle::ProcessEnter)
            .build();
        password.set_name("Password");
        sizer.add(
            &password,
            0,
            SizerFlag::AlignCenterVertical | SizerFlag::All,
            2,
        );

        let explicit_ssl = CheckBox::builder(&panel)
            .with_label("Use SS&L (AUTH SSL)")
            .build();
        // Voice control matches on the visible label, so the accessible name
        // has to start with it.
        explicit_ssl.set_name("Use SSL (AUTH SSL) with FTP");
        explicit_ssl.enable(default_protocol == Protocol::Ftp);
        sizer.add(
            &explicit_ssl,
            0,
            SizerFlag::AlignCenterVertical | SizerFlag::All,
            2,
        );

        let connect = Button::builder(&panel).with_label("&Connect").build();
        connect.set_name("Connect");
        sizer.add(
            &connect,
            0,
            SizerFlag::AlignCenterVertical | SizerFlag::All,
            2,
        );

        panel.set_sizer(sizer, true);

        Self {
            panel,
            protocol,
            host,
            port,
            username,
            password,
            explicit_ssl,
            connect,
        }
    }

    /// Fill the bar in from a saved site, ready to connect.
    pub(super) fn fill_from_site(&self, site: &portkeydrop_core::sites::Site) {
        let protocol = site.protocol();
        if let Some(index) = SUPPORTED_PROTOCOL_VALUES
            .iter()
            .position(|name| *name == protocol.as_str())
        {
            self.protocol.set_selection(index as u32);
        }
        self.host.set_value(&site.host);
        let port = if site.port > 0 {
            site.port
        } else {
            protocol.default_port(site.ftp_explicit_ssl)
        };
        self.port.set_value(&port.to_string());
        self.username.set_value(&site.username);
        self.password.set_value(&site.password);
        self.explicit_ssl.set_value(site.ftp_explicit_ssl);
        self.explicit_ssl.enable(protocol == Protocol::Ftp);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_bar_offers_every_supported_protocol() {
        // The picker is built from this list, so a protocol missing here would
        // be unreachable from the quick connect bar.
        assert_eq!(SUPPORTED_PROTOCOL_VALUES.len(), 4);
        assert!(SUPPORTED_PROTOCOL_VALUES.contains(&"sftp"));
        assert!(SUPPORTED_PROTOCOL_VALUES.contains(&"webdav"));
    }

    #[test]
    fn the_default_protocol_is_listed_first() {
        // It is what the picker selects on a fresh install.
        assert_eq!(SUPPORTED_PROTOCOL_VALUES[0], "sftp");
    }
}
