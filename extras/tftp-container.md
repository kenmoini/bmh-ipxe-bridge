# Deploy a TFTP container

If you want to boot via normal PXE you need a TFTP server, and the configure your DHCP server to point to it.

You can quickly deploy a TFTP container by running the following:

```bash
# Make some directories for things
mkdir -p /opt/c-tftp/volumes/{config,boot}

# Create a container
# Source: https://github.com/kalaksi/docker-tftpd
podman create -d \
 --name c-tftp \
 -p 69:69 \
 --cap-add=SETUID --cap-add=SETGID --cap-add=SYS_CHROOT \
 --sysctl net.ipv4.ip_unprivileged_port_start=69 \
 -e TFTPD_BIND_ADDRESS="0.0.0.0:69" \
 -e TFTPD_EXTRA_ARGS='--blocksize 1468' \
 -v /opt/c-tftp/volumes/boot:/tftpboot/boot:Z \
 -v /opt/c-tftp/volumes/config:/tftpboot/pxelinux.cfg:ro \
 registry.gitlab.com/kalaksi-containers/tftpd:latest

# Start the container
podman start c-tftp
```

You can instead optionally map the `/tftpboot/boot` volume to a path that is also under an HTTP server's path - this lets you mount artifacts over HTTP once the initial TFTP boot image has been loaded.