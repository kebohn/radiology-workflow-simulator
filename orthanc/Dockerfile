FROM jodogne/orthanc-plugins

# Bake the Orthanc configuration into the image so the service can run without bind-mounting files.
COPY orthanc.json /run/secrets/orthanc.json
