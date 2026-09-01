# Tinix Profile Bundle v1

Tinix FB Down and Tinix Social Hub use the same portable profile directory:

```text
Account-name.tinix-profile/
├── manifest.json
└── chrome-profile/
```

## Export

Open **Quản Lý Tài Khoản & Chrome Profiles**, close Chrome for the account, then choose **Export Profile**. The bundle is written under `exports/profiles/` and includes the account display name, platform, optional username, source app/version and a copied Chrome session.

## Import

Choose **Import Profile** and paste the absolute path to a `.tinix-profile` directory. FB Down creates a Facebook account with the same display name and copies the Chrome profile into its own managed profile directory.

The manifest does not contain passwords, 2FA secrets, email passwords or database cookie fields. Cache and Chrome lock files are excluded. Never open the same physical profile directory from two applications at once.
