# The CP release binaries, built from baobab-cp at the pinned merged commit on
# the runner, in CP's own production base image.
FROM gcr.io/distroless/static-debian13:nonroot
COPY controlplane migrate /
USER nonroot:nonroot
ENTRYPOINT ["/controlplane"]
