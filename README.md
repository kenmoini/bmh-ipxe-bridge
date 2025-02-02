# BareMetalHost <> iPXE Bridge

- **Container Image:** quay.io/kenmoini/bmh-ipxe-bridge:latest

```bash
oc apply -k deploy/
```

```bash
podman run --rm -d \
 --name bmh-ipxe-bridge \
 -e FLASK_URI="http://192.168.42.42:9876" \
 -p 9876:9876 \
 quay.io/kenmoini/bmh-ipxe-bridge:latest
```

```bash
dnf group install -y "Development Tools"
dnf install -y syslinux-devel genisoimage mtools xz-devel git

git clone https://github.com/ipxe/ipxe.git
cd ipxe/src

cat > script.ipxe <<EOF
#!ipxe

dhcp
chain http://boot.ipxe.org/demo/boot.php
EOF

# BIOS
make bin/undionly.kpxe EMBED=script.ipxe

# UEFI
make bin-x86_64-efi/ipxe.efi EMBED=script.ipxe
```

```
#!ipxe

dhcp
chain http://192.168.42.42:9876/ipxe-boot
```

```
#!ipxe

dhcp
chain http://bmh-ipxe-bridge-multicluster-engine.apps.endurance-sno.d70.lab.kemo.network/ipxe-boot
```
