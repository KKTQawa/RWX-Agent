package com.corrodinggames.rts.game.ai.custom.micro;

import java.util.List;
import java.util.Map;

/**
 * Read-only view of the {@code map} section of a case's {@code config.json}. Values use direct
 * JSON types; missing or wrongly typed entries fall back to the caller's default so a partial
 * config remains usable.
 */
public final class MicroTuning {
    private final Map<String,Object> root;
    public MicroTuning(Map<String,Object> root){this.root=root==null?Map.of():root;}

    public Object get(String path){
        Object value=root;
        for(String part:path.split("\\.")){
            if(!(value instanceof Map<?,?> map))return null;
            value=map.get(part);
        }
        return value;
    }
    public int integer(String path,int fallback){
        Object value=get(path);
        return value instanceof Number number?number.intValue():fallback;
    }
    public long longValue(String path,long fallback){
        Object value=get(path);
        return value instanceof Number number?number.longValue():fallback;
    }
    public double number(String path,double fallback){
        Object value=get(path);
        return value instanceof Number number?number.doubleValue():fallback;
    }
    public boolean bool(String path,boolean fallback){
        Object value=get(path);
        return value instanceof Boolean flag?flag:fallback;
    }
    public String string(String path,String fallback){
        Object value=get(path);
        return value instanceof String text?text:fallback;
    }
    @SuppressWarnings("unchecked")
    public Map<String,Object> object(String path){
        Object value=get(path);
        return value instanceof Map<?,?> map?(Map<String,Object>)map:Map.of();
    }
    public List<String> strings(String path,List<String> fallback){
        Object value=get(path);
        if(!(value instanceof List<?> list))return fallback;
        return list.stream().filter(String.class::isInstance).map(String.class::cast).toList();
    }
}
