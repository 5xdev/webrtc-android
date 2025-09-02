from __future__ import print_function

import argparse
import errno
import os
import shutil
import subprocess
import sys

# Constants

APPLE_FRAMEWORK_NAME = 'WebRTC.framework'
APPLE_DSYM_NAME = 'WebRTC.dSYM'

ANDROID_CPU_ABI_MAP = {
    'arm': 'armeabi-v7a',
    'arm64': 'arm64-v8a',
    'x86': 'x86',
    'x64': 'x86_64'
}
ANDROID_BUILD_CPUS = ['arm', 'arm64', 'x86', 'x64']
IOS_BUILD_ARCHS = ['device:arm64', 'simulator:arm64', 'simulator:x64']
MACOS_BUILD_ARCHS = ['arm64', 'x64']

# Linker flags to ensure compatibility with upcoming 16 KB page-size devices.
# common-page-size keeps smaller (4K) common alignment for better memory usage while
# max-page-size allows running on 16K page systems.
ANDROID_PAGE_SIZE_LDFLAGS = [
    'extra_ldflags=["-Wl,-z,common-page-size=4096","-Wl,-z,max-page-size=16384"]'
]

def build_gn_args(platform_args):
    return "--args='" + ' '.join(GN_COMMON_ARGS + platform_args) + "'"

GN_COMMON_ARGS = [
    'rtc_libvpx_build_vp9=true',
    'rtc_enable_protobuf=false',
    'rtc_include_tests=false',
    'is_debug=%s',
    'target_cpu="%s"'
]

_GN_APPLE_COMMON = [
    'enable_dsyms=true',
    'enable_stripping=true',
    'rtc_enable_symbol_export=false',
    'rtc_enable_objc_symbol_export=true'
]

_GN_IOS_ARGS = [
    'ios_deployment_target="12.0"',
    'ios_enable_code_signing=false',
    'target_os="ios"',
    'target_environment="%s"'
]
GN_IOS_ARGS = build_gn_args(_GN_APPLE_COMMON + _GN_IOS_ARGS)

_GN_MACOS_ARGS = [
    'target_os="mac"'
]
GN_MACOS_ARGS = build_gn_args(_GN_APPLE_COMMON + _GN_MACOS_ARGS)

# Android args now include the 16K page-size linker flags
_GN_ANDROID_ARGS = [
    'target_os="android"'
] + ANDROID_PAGE_SIZE_LDFLAGS
GN_ANDROID_ARGS = build_gn_args(_GN_ANDROID_ARGS)

def sh(cmd, env=None, cwd=None):
    print('Running cmd: %s' % cmd)
    try:
        subprocess.check_call(cmd, env=env, cwd=cwd, shell=True,
                              stdin=sys.stdin, stdout=sys.stdout, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        pass

def mkdirp(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

def rmr(path):
    try:
        shutil.rmtree(path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise

def setup(target_dir, platform):
    mkdirp(target_dir)
    os.chdir(target_dir)

    depot_tools_dir = os.path.join(target_dir, 'depot_tools')
    if not os.path.isdir(depot_tools_dir):
        print('Fetching Chromium depot_tools...')
        sh('git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git')

    env = os.environ.copy()
    env['PATH'] = '%s:%s' % (env['PATH'], depot_tools_dir)

    webrtc_dir = os.path.join(target_dir, 'webrtc', platform)
    if not os.path.isdir(webrtc_dir):
        mkdirp(webrtc_dir)
        os.chdir(webrtc_dir)
        print('Fetching WebRTC for %s...' % platform)
        sh('fetch --nohooks webrtc_%s' % platform, env)

    sh('gclient sync', env)

    if platform == 'android':
        webrtc_dir = os.path.join(target_dir, 'webrtc', platform, 'src')
        os.chdir(webrtc_dir)
        sh('./build/install-build-deps.sh')

def sync(target_dir, platform):
    depot_tools_dir = os.path.join(target_dir, 'depot_tools')
    webrtc_dir = os.path.join(target_dir, 'webrtc', platform, 'src')

    if not os.path.isdir(webrtc_dir):
        print('WebRTC source not found, did you forget to run --setup?')
        sys.exit(1)

    env = os.environ.copy()
    path_parts = [env['PATH'], depot_tools_dir]
    if platform == 'android':
        android_sdk_root = os.path.join(webrtc_dir, 'third_party/android_sdk/public')
        path_parts.append(os.path.join(android_sdk_root, 'platform-tools'))
        path_parts.append(os.path.join(android_sdk_root, 'tools'))
        path_parts.append(os.path.join(webrtc_dir, 'build/android'))
    env['PATH'] = ':'.join(path_parts)

    os.chdir(webrtc_dir)
    sh('gclient sync -D', env)

def build(target_dir, platform, debug):
    build_dir = os.path.join(target_dir, 'build', platform)
    build_type = 'Debug' if debug else 'Release'
    depot_tools_dir = os.path.join(target_dir, 'depot_tools')
    webrtc_dir = os.path.join(target_dir, 'webrtc', platform, 'src')

    if not os.path.isdir(webrtc_dir):
        print('WebRTC source not found, did you forget to run --setup?')
        sys.exit(1)

    env = os.environ.copy()
    path_parts = [env['PATH'], depot_tools_dir]
    if platform == 'android':
        android_sdk_root = os.path.join(webrtc_dir, 'third_party/android_sdk/public')
        path_parts.append(os.path.join(android_sdk_root, 'platform-tools'))
        path_parts.append(os.path.join(android_sdk_root, 'tools'))
        path_parts.append(os.path.join(webrtc_dir, 'build/android'))
    env['PATH'] = ':'.join(path_parts)

    os.chdir(webrtc_dir)

    rmr('out')

    if platform == 'ios':
        for item in IOS_BUILD_ARCHS:
            tenv, arch = item.split(':')
            gn_out_dir = f'out/{build_type}-ios-{tenv}-{arch}'
            gn_args = GN_IOS_ARGS % (str(debug).lower(), arch, tenv)
            sh(f'gn gen {gn_out_dir} {gn_args}', env)
        for arch in MACOS_BUILD_ARCHS:
            gn_out_dir = f'out/{build_type}-macos-{arch}'
            gn_args = GN_MACOS_ARGS % (str(debug).lower(), arch)
            sh(f'gn gen {gn_out_dir} {gn_args}', env)
    else:
        for cpu in ANDROID_BUILD_CPUS:
            gn_out_dir = f'out/{build_type}-{cpu}'
            gn_args = GN_ANDROID_ARGS % (str(debug).lower(), cpu)
            sh(f'gn gen {gn_out_dir} {gn_args}', env)

    if platform == 'ios':
        for item in IOS_BUILD_ARCHS:
            tenv, arch = item.split(':')
            gn_out_dir = f'out/{build_type}-ios-{tenv}-{arch}'
            sh(f'ninja -C {gn_out_dir} framework_objc', env)
        for arch in MACOS_BUILD_ARCHS:
            gn_out_dir = f'out/{build_type}-macos-{arch}'
            sh(f'ninja -C {gn_out_dir} mac_framework_objc', env)
    else:
        for cpu in ANDROID_BUILD_CPUS:
            gn_out_dir = f'out/{build_type}-{cpu}'
            # Build both targets; libjingle_peerconnection_so contains native JNI.
            sh(f'ninja -C {gn_out_dir} libwebrtc libjingle_peerconnection_so', env)

    rmr(build_dir)
    mkdirp(build_dir)

    if platform == 'ios':
        simulators = [item for item in IOS_BUILD_ARCHS if item.startswith('simulator')]
        tenv, arch = simulators[0].split(':')
        gn_out_dir = f'out/{build_type}-ios-{tenv}-{arch}'

        shutil.copytree(os.path.join(gn_out_dir, APPLE_FRAMEWORK_NAME),
                        os.path.join(gn_out_dir, 'fat-' + APPLE_FRAMEWORK_NAME))
        out_lib_path = os.path.join(gn_out_dir, 'fat-' + APPLE_FRAMEWORK_NAME, 'WebRTC')
        slice_paths = []
        for item in simulators:
            tenv, arch = item.split(':')
            lib_path = os.path.join(f'out/{build_type}-ios-{tenv}-{arch}', APPLE_FRAMEWORK_NAME, 'WebRTC')
            slice_paths.append(lib_path)
        sh('lipo %s -create -output %s' % (' '.join(slice_paths), out_lib_path))

        orig_framework_path = os.path.join(gn_out_dir, APPLE_FRAMEWORK_NAME)
        bak_framework_path = os.path.join(gn_out_dir, 'bak-' + APPLE_FRAMEWORK_NAME)
        fat_framework_path = os.path.join(gn_out_dir, 'fat-' + APPLE_FRAMEWORK_NAME)
        shutil.move(orig_framework_path, bak_framework_path)
        shutil.move(fat_framework_path, orig_framework_path)

        shutil.copytree(os.path.join(gn_out_dir, APPLE_DSYM_NAME),
                        os.path.join(gn_out_dir, 'fat-' + APPLE_DSYM_NAME))
        out_dsym_path = os.path.join(gn_out_dir, 'fat-' + APPLE_DSYM_NAME,
                                     'Contents', 'Resources', 'DWARF', 'WebRTC')
        slice_paths = []
        for item in simulators:
            tenv, arch = item.split(':')
            dsym_path = os.path.join(f'out/{build_type}-ios-{tenv}-{arch}',
                                     APPLE_DSYM_NAME, 'Contents', 'Resources', 'DWARF', 'WebRTC')
            slice_paths.append(dsym_path)
        sh('lipo %s -create -output %s' % (' '.join(slice_paths), out_dsym_path))

        orig_dsym_path = os.path.join(gn_out_dir, APPLE_DSYM_NAME)
        bak_dsym_path = os.path.join(gn_out_dir, 'bak-' + APPLE_DSYM_NAME)
        fat_dsym_path = os.path.join(gn_out_dir, 'fat-' + APPLE_DSYM_NAME)
        shutil.move(orig_dsym_path, bak_dsym_path)
        shutil.move(fat_dsym_path, orig_dsym_path)

        _IOS_BUILD_ARCHS = [item for item in IOS_BUILD_ARCHS if not item.startswith('simulator')]
        _IOS_BUILD_ARCHS.append(simulators[0])

        gn_out_dir = f'out/{build_type}-macos-{MACOS_BUILD_ARCHS[0]}'
        shutil.copytree(os.path.join(gn_out_dir, APPLE_FRAMEWORK_NAME),
                        os.path.join(gn_out_dir, 'fat-' + APPLE_FRAMEWORK_NAME), symlinks=True)
        out_lib_path = os.path.join(gn_out_dir, 'fat-' + APPLE_FRAMEWORK_NAME,
                                    'Versions', 'Current', 'WebRTC')
        slice_paths = []
        for arch in MACOS_BUILD_ARCHS:
            lib_path = os.path.join(f'out/{build_type}-macos-{arch}',
                                    APPLE_FRAMEWORK_NAME, 'Versions', 'Current', 'WebRTC')
            slice_paths.append(lib_path)
        sh('lipo %s -create -output %s' % (' '.join(slice_paths), out_lib_path))

        orig_framework_path = os.path.join(gn_out_dir, APPLE_FRAMEWORK_NAME)
        bak_framework_path = os.path.join(gn_out_dir, 'bak-' + APPLE_FRAMEWORK_NAME)
        fat_framework_path = os.path.join(gn_out_dir, 'fat-' + APPLE_FRAMEWORK_NAME)
        shutil.move(orig_framework_path, bak_framework_path)
        shutil.move(fat_framework_path, orig_framework_path)

        shutil.copytree(os.path.join(gn_out_dir, APPLE_DSYM_NAME),
                        os.path.join(gn_out_dir, 'fat-' + APPLE_DSYM_NAME))
        out_dsym_path = os.path.join(gn_out_dir, 'fat-' + APPLE_DSYM_NAME,
                                     'Contents', 'Resources', 'DWARF', 'WebRTC')
        slice_paths = []
        for arch in MACOS_BUILD_ARCHS:
            dsym_path = os.path.join(f'out/{build_type}-macos-{arch}',
                                     APPLE_DSYM_NAME, 'Contents', 'Resources', 'DWARF', 'WebRTC')
            slice_paths.append(dsym_path)
        sh('lipo %s -create -output %s' % (' '.join(slice_paths), out_dsym_path))

        xcframework_path = os.path.join(build_dir, 'WebRTC.xcframework')
        xcodebuild_cmd = 'xcodebuild -create-xcframework -output %s' % xcframework_path
        for item in _IOS_BUILD_ARCHS:
            tenv, arch = item.split(':')
            gn_out_dir = f'out/{build_type}-ios-{tenv}-{arch}'
            xcodebuild_cmd += ' -framework %s' % os.path.abspath(os.path.join(gn_out_dir, APPLE_FRAMEWORK_NAME))
            xcodebuild_cmd += ' -debug-symbols %s' % os.path.abspath(os.path.join(gn_out_dir, APPLE_DSYM_NAME))
        gn_out_dir = f'out/{build_type}-macos-{MACOS_BUILD_ARCHS[0]}'
        xcodebuild_cmd += ' -framework %s' % os.path.abspath(os.path.join(gn_out_dir, APPLE_FRAMEWORK_NAME))
        xcodebuild_cmd += ' -debug-symbols %s' % os.path.abspath(os.path.join(gn_out_dir, APPLE_DSYM_NAME))
        sh(xcodebuild_cmd)
        sh('zip -y -r WebRTC.xcframework.zip WebRTC.xcframework', cwd=build_dir)
    else:
        gn_out_dir = f'out/{build_type}-{ANDROID_BUILD_CPUS[0]}'
        shutil.copy(os.path.join(gn_out_dir, 'lib.java/sdk/android/libwebrtc.jar'), build_dir)
        for cpu in ANDROID_BUILD_CPUS:
            lib_dir = os.path.join(build_dir, ANDROID_CPU_ABI_MAP[cpu])
            mkdirp(lib_dir)
            gn_out_dir = f'out/{build_type}-{cpu}'
            shutil.copy(os.path.join(gn_out_dir, 'libjingle_peerconnection_so.so'), lib_dir)
        sh('zip -r android-webrtc.zip *', cwd=build_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('dir', help='Target directory')
    parser.add_argument('--setup', action='store_true', help='Prepare the target directory for building')
    parser.add_argument('--build', action='store_true', help='Build WebRTC in the target directory')
    parser.add_argument('--sync', action='store_true', help='Runs gclient sync on the WebRTC directory')
    parser.add_argument('--ios', action='store_true', help='Use iOS as the target platform')
    parser.add_argument('--android', action='store_true', help='Use Android as the target platform')
    parser.add_argument('--debug', action='store_true', help='Make a Debug build (defaults to Release)')

    args = parser.parse_args()

    if not (args.setup or args.build or args.sync):
        print('--setup or --build or --sync must be specified!')
        sys.exit(1)
    if sum([args.setup, args.build]) > 1:
        print('--setup and --build cannot be specified together!')
        sys.exit(1)
    if not (args.ios or args.android):
        print('--ios or --android must be specified!')
        sys.exit(1)
    if args.ios and args.android:
        print('--ios and --android cannot be specified at the same time!')
        sys.exit(1)
    if not os.path.isdir(args.dir):
        print('The specified directory does not exist!')
        sys.exit(1)

    target_dir = os.path.abspath(os.path.join(args.dir, 'build_webrtc'))
    platform = 'ios' if args.ios else 'android'

    if args.setup:
        setup(target_dir, platform)
        print('WebRTC setup for %s completed in %s' % (platform, target_dir))
        sys.exit(0)
    if args.sync:
        sync(target_dir, platform)
        print('WebRTC sync for %s completed in %s' % (platform, target_dir))
        sys.exit(0)
    if args.build:
        build(target_dir, platform, args.debug)
        print('WebRTC build for %s completed in %s' % (platform, target_dir))
        sys.exit(0)