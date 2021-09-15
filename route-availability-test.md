   ``` 
   enter candidate 
   /routing-policy
    prefix-set dns {
        prefix 8.8.8.8/32 mask-length-range 32..32 {
        }
    }
    policy no-dns {
        default-action {
            accept {
            }
        }
        statement 10 {
            match {
                prefix-set dns
                protocol bgp-evpn
            }
            action {
                reject {
                }
            }
        }
    }
/network-instance default protocols bgp group evpn import-policy no-dns    
commit stay
```

