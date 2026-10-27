package riffuna.core

object TextMatch {
    fun ratio(a:String,b:String):Double {
        if(a==b)return 1.0;if(a.isEmpty()||b.isEmpty())return 0.0
        fun matches(a0:Int,a1:Int,b0:Int,b1:Int):Int {
            var best=0;var ai=a0;var bi=b0;var prev=IntArray(b1-b0+1)
            for(i in a0 until a1){val next=IntArray(b1-b0+1);for(j in b0 until b1)if(a[i]==b[j]){val n=prev[j-b0]+1;next[j-b0+1]=n;if(n>best){best=n;ai=i-n+1;bi=j-n+1}};prev=next}
            return if(best==0)0 else best+matches(a0,ai,b0,bi)+matches(ai+best,a1,bi+best,b1)
        }
        return 2.0*matches(0,a.length,0,b.length)/(a.length+b.length)
    }
}
