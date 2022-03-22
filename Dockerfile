FROM debian:buster
EXPOSE 8080
RUN apt update
RUN apt install -y git curl openssl libssl-dev pkg-config
RUN apt install -y libsodium-dev clang libclang-dev llvm llvm-dev libev-dev
RUN apt install -y make python3 python3-pip
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3 1
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1
RUN git clone https://github.com/tezedge/tezedge --branch develop
RUN cp -r /tezedge /tezedge_fuzz
RUN git clone https://github.com/tezedge/fuzzcheck-rs
ENV RUSTUP_HOME=/rust
ENV CARGO_HOME=/cargo
ENV PATH=/cargo/bin:/rust/bin:$PATH
ARG rust_toolchain="nightly-2021-11-21"
RUN curl https://sh.rustup.rs -sSf | sh -s -- --default-toolchain ${rust_toolchain} -y --no-modify-path
RUN cd fuzzcheck-rs && cargo install --path ./cargo-fuzzcheck/
RUN pip install quart psutil async-timeout
RUN mkdir /static
COPY web-files /static/web-files
COPY ./server.py /server.py
COPY ./report.py /report.py
CMD python /server.py
