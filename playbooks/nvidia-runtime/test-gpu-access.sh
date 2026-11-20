#!/usr/bin/env bash
# Run on the workstation AFTER deploying the host fix and both Compose files.
# Uses disposable containers with no media, queue, network, or published ports.
# WARNING: daemon-reload is host-wide; schedule around unprotected GPU workloads.
set -euo pipefail

probes=()
cleanup() {
    if ((${#probes[@]})); then
        docker rm -f "${probes[@]}" >/dev/null
    fi
}
trap cleanup EXIT

encode() {
    local container=$1 ffmpeg=$2
    docker exec "$container" "$ffmpeg" -hide_banner -loglevel error \
        -init_hw_device cuda=cu:0 -f lavfi -i color=size=128x128:rate=24 \
        -t 1 -c:v h264_nvenc -f null -
}

sudo -n true
sources=(jellyfin arr-prepare-1)
encoders=(/usr/lib/jellyfin-ffmpeg/ffmpeg /usr/bin/ffmpeg)
for i in 0 1; do
    source=${sources[$i]}
    name="nvidia-access-${source}-$$"
    image=$(docker inspect "$source" --format '{{.Image}}')
    probes+=("$name")
    docker run -d --name "$name" --network none --runtime nvidia \
        --gpus '"capabilities=gpu,video"' \
        -e NVIDIA_DRIVER_CAPABILITIES=video,utility,compute \
        --device /dev/nvidia0:/dev/nvidia0:rw \
        --device /dev/nvidiactl:/dev/nvidiactl:rw \
        --device /dev/nvidia-uvm:/dev/nvidia-uvm:rw \
        --device /dev/nvidia-uvm-tools:/dev/nvidia-uvm-tools:rw \
        --user 1000:1000 --read-only --cap-drop ALL \
        --security-opt no-new-privileges:true \
        --entrypoint /bin/sh "$image" -c 'exec sleep 600' >/dev/null
    encode "$name" "${encoders[$i]}"
    echo "$source: baseline NVENC passed"
    docker update --cpus 1 "$name" >/dev/null
    encode "$name" "${encoders[$i]}"
    echo "$source: NVENC after resource update passed"
done

sudo -n systemctl daemon-reload
for i in 0 1; do
    encode "${probes[$i]}" "${encoders[$i]}"
    encode "${sources[$i]}" "${encoders[$i]}"
    echo "${sources[$i]}: disposable and live NVENC after daemon-reload passed"
done
