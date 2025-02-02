# podman build -t bmh-ipxe-bridge -f Containerfile .
# podman push bmh-ipxe-bridge quay.io/kenmoini/bmh-ipxe-bridge:latest
# podman run --name bmh-ipxe-bridge --rm -p 8675:8675 -v /opt/isos:/opt/isos -v /opt/job-codes:/opt/job-codes jobcode-api

#FROM quay.io/kenmoini/job-code-base:latest
FROM registry.fedoraproject.org/fedora:41

ENV FLASK_RUN_PORT=9876
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASH_TLS_CERT=
ENV FLASH_TLS_KEY=

USER 0

WORKDIR /opt/app-root/src
COPY ./container_root /

RUN dnf update -y \
 && dnf install -y python3 python3-pip openssl \
 && dnf clean all \
 && rm -rf /var/cache/yum \
 && pip3 install -r /opt/app-root/src/requirements.txt \ 
 && chmod a+x /opt/app-root/start.sh

USER 1001

EXPOSE 9876

CMD ["/opt/app-root/start.sh"]