# calendar-gates API image. Local: `just image`; CI: docker/build-push-action.
# Base images are pinned by multi-arch index digest; Dependabot (docker) keeps them current.

# Build on the builder's own platform: the output is portable IL (framework-dependent, no
# RID), so the same publish runs on every target platform without QEMU-emulated builds.
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:11.0@sha256:65f3c7c6a25a239ab3e6719f2896147e7b68242ff2d8818dd70498bde6ef8bea AS build
WORKDIR /src

# Restore layer: only what restore needs, so source edits don't invalidate the package cache
COPY global.json Directory.Build.props Directory.Packages.props ./
COPY src/CalendarGates.Api/CalendarGates.Api.csproj src/CalendarGates.Api/packages.lock.json src/CalendarGates.Api/
RUN dotnet restore src/CalendarGates.Api --locked-mode

COPY src/ src/

# .git is not in the build context: the version comes in as a build arg (MinVer would
# otherwise warn, and warnings are errors), the commit too.
ARG VERSION=0.0.0-docker
ARG COMMIT=unknown
RUN dotnet publish src/CalendarGates.Api --no-restore -c Release -o /app \
    -p:UseAppHost=false \
    -p:MinVerVersionOverride="$VERSION" \
    -p:Commit="$COMMIT" \
    -p:EnableSourceControlManagerQueries=false

# Runtime: Ubuntu 26.04 (resolute) chiseled, no shell or package manager, runs as the non-root `app` user (1654)
FROM mcr.microsoft.com/dotnet/aspnet:11.0-resolute-chiseled@sha256:fc0ee12f9ea79bde6cda88c7a34e5467fe383dbb62276be0ec13e5e9cc1654ac AS runtime
LABEL org.opencontainers.image.title="calendar-gates" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/gergodrazsdik/calendar-gates"
WORKDIR /app
COPY --from=build /app ./
# The image's appsettings never change, so don't watch them: each watcher takes an inotify
# instance, and a host running several kind clusters runs out (docs/adr/0010-admission-control.md).
ENV DOTNET_hostBuilder__reloadConfigOnChange=false
# The numeric uid, not the `app` name: Kubernetes cannot verify `runAsNonRoot` against a user name
# ("cannot verify user is non-root"), which is why the chart has to repeat the number in
# `runAsUser`. 1654 is the base image's own APP_UID, and its Config.User is already numeric —
# `USER app` was replacing a number with a name. hadolint 2.15 flags that as DL3066.
USER 1654
EXPOSE 8080
ENTRYPOINT ["dotnet", "CalendarGates.Api.dll"]
