# App-specific R8 rules for the release build.
#
# This file is picked up AUTOMATICALLY — there is no reference to it in
# build.gradle.kts and there must not be one. The Flutter Gradle Plugin adds it
# if and only if it exists (FlutterPlugin.kt:222-225), alongside
# proguard-android-optimize.txt and flutter_proguard_rules.pro:
#
#     val proguardRulesPro = File("${project.projectDir}/proguard-rules.pro")
#     if (proguardRulesPro.exists()) { releaseBuildType.proguardFiles.add(proguardRulesPro) }
#
# Deliberately NO keep rules for Firebase, Cashfree or Google Places. All three
# ship their own consumer rules inside their AARs and AGP merges them already —
# Cashfree keeps com.cashfree.pg.{api,ui.api,core}.**, Places keeps
# com.google.android.libraries.places.** (it arrives pre-obfuscated), and
# firebase-auth/firebase-common bring theirs. Re-stating them here as broad
# wildcards would only block optimization R8 is otherwise free to do, which is
# the opposite of the intent, and would mask a real breakage behind a rule that
# looks protective. Add a rule here only when a release-only failure proves one
# is missing, and scope it to the class that actually failed.

# Deobfuscatable crash traces.
#
# proguard-android-optimize.txt does NOT retain these, so a production stack
# trace from this app currently arrives with no line numbers and cannot be fully
# resolved even when mapping.txt is applied. For a payment flow that is the
# difference between "Cashfree checkout crashed somewhere" and a file and line.
#
# -renamesourcefileattribute collapses every source filename to the literal
# "SourceFile", so keeping LineNumberTable does NOT leak the original .java/.kt
# names; retrace restores them from mapping.txt. Costs a few hundred KB.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
