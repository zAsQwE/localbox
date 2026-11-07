//go:build android && cgo

#include <jni.h>
#include <stdlib.h>
#include <string.h>

extern char *LocalBoxStart(char *, char *, int, int);
extern void LocalBoxStop(void);
extern char *LocalBoxStatus(void);
extern void LocalBoxSpeechState(int, char *);
extern char *LocalBoxSpeechNext(void);
extern void LocalBoxSpeechDone(char *, char *);

static jstring utf8_string(JNIEnv *env, const char *value) {
    if (!value) return NULL;
    jbyteArray bytes = (*env)->NewByteArray(env, (jsize)strlen(value));
    (*env)->SetByteArrayRegion(env, bytes, 0, (jsize)strlen(value), (const jbyte *)value);
    jclass type = (*env)->FindClass(env, "java/lang/String");
    jmethodID ctor = (*env)->GetMethodID(env, type, "<init>", "([BLjava/lang/String;)V");
    jstring encoding = (*env)->NewStringUTF(env, "UTF-8");
    return (jstring)(*env)->NewObject(env, type, ctor, bytes, encoding);
}

JNIEXPORT jstring JNICALL Java_tv_localbox_vpn_NativeServer_start(JNIEnv *env, jobject self,
        jstring directory, jstring host, jint game_port, jint web_port) {
    const char *dir = (*env)->GetStringUTFChars(env, directory, NULL);
    const char *address = (*env)->GetStringUTFChars(env, host, NULL);
    char *error = LocalBoxStart((char *)dir, (char *)address, game_port, web_port);
    (*env)->ReleaseStringUTFChars(env, directory, dir);
    (*env)->ReleaseStringUTFChars(env, host, address);
    jstring result = utf8_string(env, error);
    free(error);
    return result;
}

JNIEXPORT void JNICALL Java_tv_localbox_vpn_NativeServer_stop(JNIEnv *env, jobject self) { LocalBoxStop(); }

JNIEXPORT jstring JNICALL Java_tv_localbox_vpn_NativeServer_status(JNIEnv *env, jobject self) {
    char *value = LocalBoxStatus();
    jstring result = utf8_string(env, value);
    free(value);
    return result;
}

JNIEXPORT void JNICALL Java_tv_localbox_vpn_NativeServer_speechState(JNIEnv *env, jobject self, jboolean ready, jstring message) {
    const char *text=(*env)->GetStringUTFChars(env,message,NULL);
    LocalBoxSpeechState(ready,(char *)text);
    (*env)->ReleaseStringUTFChars(env,message,text);
}
JNIEXPORT jstring JNICALL Java_tv_localbox_vpn_NativeServer_speechNext(JNIEnv *env, jobject self) {
    char *value=LocalBoxSpeechNext();
    jstring result=utf8_string(env,value);free(value);return result;
}
JNIEXPORT void JNICALL Java_tv_localbox_vpn_NativeServer_speechDone(JNIEnv *env, jobject self, jstring id, jstring failure) {
    const char *key=(*env)->GetStringUTFChars(env,id,NULL);
    const char *error=(*env)->GetStringUTFChars(env,failure,NULL);
    LocalBoxSpeechDone((char *)key,(char *)error);
    (*env)->ReleaseStringUTFChars(env,id,key);
    (*env)->ReleaseStringUTFChars(env,failure,error);
}
