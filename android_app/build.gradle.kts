plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "es.dew.assistant"
    compileSdk = 35

    defaultConfig {
        applicationId = "es.dew.assistant"
        minSdk = 29 // Android 10+ (Soporte Vulkan 1.1 y Scoped Storage para GGUF)
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0-mvp"

        ndk {
            // Solo 64-bit ARM para inferencia SIMD / Vulkan de Qwen3.8-9B-Distill y Sherpa-ONNX
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
        externalNativeBuild {
            cmake {
                cppFlags += "-std=c++17 -O3 -DNDEBUG"
                arguments += listOf("-DGGML_VULKAN=ON", "-DGGML_OPENMP=OFF")
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }
}

dependencies {
    // Jetpack Compose Material 3
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")

    // SQLCipher para cifrado AES-256 local + AndroidX Biometric para acciones críticas y trámites
    implementation("net.zetetic:sqlcipher-android:4.6.1@aar")
    implementation("androidx.sqlite:sqlite-ktx:2.4.0")
    implementation("androidx.biometric:biometric:1.1.0")

    // ML Kit Offline: OCR de tickets de compra y códigos de barras EAN-13 (100% en dispositivo)
    implementation("com.google.mlkit:text-recognition:16.0.1")
    implementation("com.google.mlkit:barcode-scanning:17.3.0")

    // Suite de pruebas unitarias y de estrés JVM para garantizar 0 bloqueos táctiles
    testImplementation("junit:junit:4.13.2")
}
