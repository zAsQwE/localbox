package tv.localbox.vpn

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Append one Android boolean attribute without decoding/rebuilding resources.arsc. */
object BinaryManifest {
    private const val CLEAR_TEXT = 0x010104ec
    private fun u16(b: ByteArray, o: Int) = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getShort(o).toInt() and 65535
    private fun u32(b: ByteArray, o: Int) = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getInt(o)
    private fun put16(b: ByteArray, o: Int, n: Int) { ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).putShort(o, n.toShort()) }
    private fun put32(b: ByteArray, o: Int, n: Int) { ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).putInt(o, n) }
    private fun intBytes(n: Int) = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(n).array()

    private fun length8(n: Int): ByteArray { require(n<32768) { "Слишком длинная строка манифеста" }
        return if(n<128) byteArrayOf(n.toByte()) else byteArrayOf(((n shr 8) or 128).toByte(),n.toByte()) }
    private fun length16(n: Int): ByteArray { require(n<32768) { "Слишком длинная строка манифеста" }
        return byteArrayOf(n.toByte(),(n shr 8).toByte()) }

    private data class Chunk(val kind: Int, var bytes: ByteArray)
    data class Info(val packageName: String,val split: String,val version: String,val requiresSplits: Boolean)
    private class Pool(val b: ByteArray) {
        val count = u32(b, 8)
        val header = u16(b, 2)
        val start = u32(b, 20)
        val utf8 = u32(b, 16) and 256 != 0
        init { require(header>=28 && count>=0 && start>=header+count.toLong()*4 && start<=b.size) { "Повреждена таблица строк манифеста" } }
        fun string(index: Int): String {
            require(index in 0 until count)
            var p = start + u32(b, header + index*4)
            fun length8(): Int { val a = b[p++].toInt() and 255; return if (a and 128 == 0) a else ((a and 127) shl 8) or (b[p++].toInt() and 255) }
            fun length16(): Int { val a = u16(b, p); p+=2; return if (a and 32768 == 0) a else { val c=u16(b,p); p+=2; ((a and 32767) shl 16) or c } }
            return if (utf8) { length8(); val size=length8(); String(b, p, size, Charsets.UTF_8) }
            else { val size=length16(); String(b,p,size*2,Charsets.UTF_16LE) }
        }
        fun append(value: String): ByteArray {
            // Styles, if present, follow string data; preserve their relative offsets and contents.
            val oldStyleStart=u32(b,24)
            val dataEnd=if(oldStyleStart==0) b.size else oldStyleStart
            val offset=dataEnd-start
            val encoded=if(utf8) { val bytes=value.toByteArray();length8(value.length)+length8(bytes.size)+bytes+byteArrayOf(0) }
                else length16(value.length)+value.toByteArray(Charsets.UTF_16LE)+byteArrayOf(0,0)
            val padding=ByteArray((4-encoded.size%4)%4)
            val result=b.copyOfRange(0,header+count*4)+intBytes(offset)+b.copyOfRange(header+count*4,dataEnd)+encoded+padding+b.copyOfRange(dataEnd,b.size)
            put32(result,4,result.size);put32(result,8,count+1);put32(result,16,u32(b,16) and 1.inv());put32(result,20,start+4)
            if(oldStyleStart!=0) put32(result,24,oldStyleStart+4+encoded.size+padding.size)
            return result
        }
    }

    fun info(original: ByteArray): Info {
        require(original.size>=8 && u16(original,0)==3 && u32(original,4)==original.size) { "Некорректный манифест APK" }
        var position=u16(original,2);var pool: Pool?=null
        while(position+8<=original.size) {
            val kind=u16(original,position);val size=u32(original,position+4)
            require(size>=8 && size<=original.size-position)
            val b=original.copyOfRange(position,position+size)
            if(kind==1) pool=Pool(b)
            if(kind==0x102 && pool?.string(u32(b,20))=="manifest") {
                val strings=pool;val start=16+u16(b,24);val count=u16(b,28)
                require(u16(b,26)==20 && start+count*20<=b.size)
                val values=(0 until count).associate { index ->
                    val offset=start+index*20;val type=b[offset+15].toInt() and 255;val data=u32(b,offset+16)
                    strings.string(u32(b,offset+4)) to if(type==3) strings.string(data) else (data.toLong() and 0xffffffffL).toString()
                }
                return Info(values["package"] ?: error("Нет имени пакета"),values["split"].orEmpty(),
                    "${values["versionCodeMajor"] ?: "0"}:${values["versionCode"] ?: "0"}",values["isSplitRequired"]?.let { it!="0" } ?: false)
            }
            position+=size
        }
        error("В APK нет корневого манифеста")
    }

    fun allowLocalHttp(original: ByteArray): ByteArray {
        require(original.size>=8 && u16(original,0)==3 && u32(original,4)==original.size) { "Неподдерживаемый AndroidManifest.xml" }
        val chunks=mutableListOf<Chunk>();var position=u16(original,2)
        while(position<original.size) {
            require(position+8<=original.size)
            val size=u32(original,position+4)
            require(size>=u16(original,position+2) && size>=8 && size<=original.size-position)
            chunks.add(Chunk(u16(original,position),original.copyOfRange(position,position+size)));position+=size
        }
        val poolChunk=chunks.single { it.kind==1 };var pool=Pool(poolChunk.bytes)
        val strings=(0 until pool.count).map { pool.string(it) }
        val namespace=strings.indexOf("http://schemas.android.com/apk/res/android")
        require(namespace>=0) { "В манифесте нет пространства имён Android" }
        val app=chunks.single { it.kind==0x102 && pool.string(u32(it.bytes,20))=="application" }
        var name=strings.indexOf("usesCleartextTraffic")
        if(name<0) { name=pool.count;poolChunk.bytes=pool.append("usesCleartextTraffic");pool=Pool(poolChunk.bytes) }
        var resource=chunks.find { it.kind==0x180 }
        if(resource==null) { resource=Chunk(0x180,byteArrayOf(0x80.toByte(),1,8,0,8,0,0,0));chunks.add(chunks.indexOf(poolChunk)+1,resource) }
        resource.bytes=resource.bytes.copyOf(maxOf(resource.bytes.size,8+(name+1)*4))
        put32(resource.bytes,4,resource.bytes.size);put32(resource.bytes,8+name*4,CLEAR_TEXT)
        val b=app.bytes;val attrStart=16+u16(b,24);val attrSize=u16(b,26);val count=u16(b,28)
        require(attrSize==20 && attrStart>=36 && attrStart+count*20<=b.size)
        val attributes=(0 until count).map { b.copyOfRange(attrStart+it*20,attrStart+(it+1)*20) }.toMutableList()
        val existing=attributes.indexOfFirst { u32(it,0)==namespace && u32(it,4)==name }
        val attribute=ByteArray(20).apply { put32(this,0,namespace);put32(this,4,name);put32(this,8,-1);put16(this,12,8);this[15]=0x12;put32(this,16,-1) }
        if(existing>=0) attributes[existing]=attribute else attributes.add(attribute)
        // Resource IDs, rather than string indexes, define Android's attribute lookup order.
        fun id(a: ByteArray): Int { val i=u32(a,4);return if(i>=0 && 8+i*4+4<=resource.bytes.size) u32(resource.bytes,8+i*4) else 0 }
        val oldAttributes=attributes.take(count).toList()
        attributes.sortBy { id(it) }
        val output=ByteArrayOutputStream();output.write(b,0,attrStart);attributes.forEach { output.write(it) };output.write(b,attrStart+count*20,b.size-attrStart-count*20)
        app.bytes=output.toByteArray();put32(app.bytes,4,app.bytes.size);put16(app.bytes,28,attributes.size)
        // Preserve special indexes (id/class/style) when sorting inserts a new attribute.
        for(offset in listOf(30,32,34)) { val old=u16(b,offset);if(old>0) { val previous=oldAttributes[old-1];put16(app.bytes,offset,attributes.indexOfFirst { it.contentEquals(previous) }+1) } }
        val result=ByteArrayOutputStream();result.write(original,0,u16(original,2));chunks.forEach { result.write(it.bytes) }
        return result.toByteArray().also { put32(it,4,it.size) }
    }

    private val COMPONENTS=setOf("application","activity","activity-alias","service","receiver","provider")
    private val CLASS_ATTRIBUTES=setOf("name","targetActivity","backupAgent","manageSpaceActivity","parentActivityName")
    private val PERMISSION_DECLARATIONS=setOf("permission","permission-group","permission-tree")
    private val PERMISSION_ATTRIBUTES=setOf("name","permission","readPermission","writePermission","permissionGroup")
    private const val NO_INDEX=-1

    /** The package name a copy gets so it installs next to the original instead of over it. */
    fun copyPackage(original: String): String = if(original.endsWith(".localbox")) original else "$original.localbox"

    /**
     * Give the manifest another package name so Android installs the copy next to the original.
     * Relative component names are made absolute (classes keep their Java package), and names that
     * must be unique per device (provider authorities, declared permissions) follow the new package.
     * [label] replaces the application label (and activity labels equal to it) when given.
     */
    fun retarget(original: ByteArray,newPackage: String,label: String?=null): ByteArray {
        require(newPackage.matches(Regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+")) && newPackage.length<128) { "Неверное имя пакета" }
        require(original.size>=8 && u16(original,0)==3 && u32(original,4)==original.size) { "Неподдерживаемый AndroidManifest.xml" }
        val chunks=mutableListOf<Chunk>();var position=u16(original,2)
        while(position<original.size) {
            require(position+8<=original.size)
            val size=u32(original,position+4)
            require(size>=u16(original,position+2) && size>=8 && size<=original.size-position)
            chunks.add(Chunk(u16(original,position),original.copyOfRange(position,position+size)));position+=size
        }
        val poolChunk=chunks.single { it.kind==1 };var pool=Pool(poolChunk.bytes)
        val namespace=(0 until pool.count).firstOrNull { pool.string(it)=="http://schemas.android.com/apk/res/android" } ?: NO_INDEX
        fun intern(value: String): Int {
            (0 until pool.count).firstOrNull { pool.string(it)==value }?.let { return it }
            val index=pool.count;poolChunk.bytes=pool.append(value);pool=Pool(poolChunk.bytes);return index
        }
        class Attribute(val chunk: Chunk,val offset: Int,val element: String) {
            val b get()=chunk.bytes
            val ns get()=u32(b,offset)
            val name get()=pool.string(u32(b,offset+4))
            val android get()=namespace!=NO_INDEX && ns==namespace
            val type get()=b[offset+15].toInt() and 255
            val data get()=u32(b,offset+16)
            val text: String? get()=if(type==3) pool.string(data) else u32(b,offset+8).takeIf { it!=-1 }?.let { pool.string(it) }
            fun set(value: String) { val index=intern(value);put32(b,offset+8,index);put16(b,offset+12,8);b[offset+14]=0;b[offset+15]=3;put32(b,offset+16,index) }
        }
        val attributes=chunks.filter { it.kind==0x102 }.flatMap { chunk ->
            val b=chunk.bytes;val element=pool.string(u32(b,20));val start=16+u16(b,24);val count=u16(b,28)
            require(u16(b,26)==20 && start+count*20<=b.size) { "Повреждён элемент манифеста" }
            (0 until count).map { Attribute(chunk,start+it*20,element) }
        }
        val packageAttribute=attributes.single { it.element=="manifest" && it.ns==-1 && it.name=="package" }
        val oldPackage=packageAttribute.text ?: error("Нет имени пакета")
        val suffix=if(newPackage.startsWith("$oldPackage.")) newPackage.removePrefix(oldPackage) else ".localbox"
        fun unique(value: String)=when {
            oldPackage==newPackage -> value
            value==oldPackage || value.startsWith("$oldPackage.") -> newPackage+value.removePrefix(oldPackage)
            else -> value+suffix
        }
        // Component classes resolve against the package: keep them pointing at the original classes.
        for(a in attributes) if(a.android && a.element in COMPONENTS && a.name in CLASS_ATTRIBUTES) {
            val value=a.text ?: continue
            if(value.startsWith(".")) a.set(oldPackage+value) else if(!value.contains('.') && value.isNotEmpty()) a.set("$oldPackage.$value")
        }
        val permissions=attributes.filter { it.android && it.element in PERMISSION_DECLARATIONS && it.name=="name" }
            .mapNotNull { it.text }.associateWith { unique(it) }
        for(a in attributes) {
            if(!a.android) continue
            val value=a.text ?: continue
            when {
                a.element=="provider" && a.name=="authorities" -> a.set(value.split(';').joinToString(";") { unique(it) })
                a.name in PERMISSION_ATTRIBUTES && value in permissions -> a.set(permissions.getValue(value))
            }
        }
        if(label!=null) {
            val appLabel=attributes.firstOrNull { it.android && it.element=="application" && it.name=="label" }
            if(appLabel!=null) {
                val before=appLabel.type to appLabel.data
                for(a in attributes) if(a.android && a.name=="label" && a.element in setOf("activity","activity-alias") && (a.type to a.data)==before) a.set(label)
                appLabel.set(label)
            }
        }
        packageAttribute.set(newPackage)
        val result=ByteArrayOutputStream();result.write(original,0,u16(original,2));chunks.forEach { result.write(it.bytes) }
        return result.toByteArray().also { put32(it,4,it.size) }
    }

    /** (element, attribute, string value) of every string attribute, for checks and diagnostics. */
    fun strings(original: ByteArray): List<Triple<String,String,String>> {
        var position=u16(original,2);var pool: Pool?=null;val out=mutableListOf<Triple<String,String,String>>()
        while(position+8<=original.size) {
            val size=u32(original,position+4);require(size>=8 && size<=original.size-position)
            val b=original.copyOfRange(position,position+size)
            if(u16(b,0)==1) pool=Pool(b)
            if(u16(b,0)==0x102 && pool!=null) {
                val element=pool.string(u32(b,20));val start=16+u16(b,24)
                for(i in 0 until u16(b,28)) {
                    val o=start+i*20;val raw=u32(b,o+8)
                    val value=if(b[o+15].toInt() and 255==3) pool.string(u32(b,o+16)) else if(raw!=-1) pool.string(raw) else continue
                    out.add(Triple(element,pool.string(u32(b,o+4)),value))
                }
            }
            position+=size
        }
        return out
    }

    /** Rename the package chunk of resources.arsc (fixed 128-char field, size unchanged); null if absent. */
    fun retargetResources(original: ByteArray,oldPackage: String,newPackage: String): ByteArray? {
        require(original.size>=12 && u16(original,0)==2 && u32(original,4)<=original.size) { "Неподдерживаемый resources.arsc" }
        require(newPackage.length<128)
        val result=original.copyOf();var changed=false;var position=u16(original,2)
        while(position+8<=result.size) {
            val kind=u16(result,position);val size=u32(result,position+4)
            require(size>=8 && size<=result.size-position) { "Повреждён resources.arsc" }
            if(kind==0x200 && size>=12+256) {
                val raw=String(result,position+12,256,Charsets.UTF_16LE);val name=raw.substringBefore('\u0000')
                if(name==oldPackage) {
                    val encoded=newPackage.toByteArray(Charsets.UTF_16LE)
                    java.util.Arrays.fill(result,position+12,position+12+256,0);System.arraycopy(encoded,0,result,position+12,encoded.size);changed=true
                }
            }
            position+=size
        }
        return if(changed) result else null
    }
}
