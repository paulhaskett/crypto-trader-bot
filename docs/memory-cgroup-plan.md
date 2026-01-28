# Memory Cgroup Implementation Plan
## For Crypto Trading Bot on Raspberry Pi

**Purpose:** Enable memory cgroup support to fix Docker memory warnings and prepare for multi-project containerization
**Impact:** Single reboot required, resolves memory limit warnings
**Timeline:** ~15 minutes + reboot

---

## CURRENT STATE (Before Implementation)
- **Kernel:** 6.12.62+rpt-rpi-2712
- **RAM:** 15.83GB total, 10GB available  
- **Docker Warnings:** `WARNING: No memory limit support` and `WARNING: No swap limit support`
- **Memory Controller Status:** Missing from `/proc/cgroups` (not enabled)
- **Current cmdline.txt:** 
  ```
  console=serial0,115200 console=tty1 root=PARTUUID=a3214903-02 rootfstype=ext4 fsck.repair=yes rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=GB
  ```

---

## IMPLEMENTATION STEPS

### Phase 1: System Preparation (Agent Executes Before Reboot)

#### 1.1 Backup Current Configuration
```bash
sudo cp /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.backup
# Verify backup created
ls -la /boot/firmware/cmdline.txt*
```

#### 1.2 Create Updated Kernel Parameters
```bash
# Add memory cgroup parameters to cmdline.txt
sudo sh -c 'echo "$(cat /boot/firmware/cmdline.txt) cgroup_enable=memory systemd.unified_cgroup_hierarchy=0" > /boot/firmware/cmdline.txt'

# Verify the change
cat /boot/firmware/cmdline.txt
# Expected: original line + " cgroup_enable=memory systemd.unified_cgroup_hierarchy=0"
```

#### 1.3 Update docker-compose.yml for Post-Reboot Testing
```yaml
# In services.crypto-trader-bot.deploy.resources section:
deploy:
  resources:
    limits:
      memory: 1.5G
      swap: 1.8G
    reservations:
      memory: 512M
```

#### 1.4 Save Current System State for Reference
```bash
# Save current cgroups state
cp /proc/cgroups /tmp/cgroups_before.txt
echo "Current cgroups saved to /tmp/cgroups_before.txt"

# Save current docker warnings
docker info > /tmp/docker_info_before.txt 2>&1
echo "Current docker info saved to /tmp/docker_info_before.txt"
```

### Phase 2: Manual Verification (User Executes After Reboot)

#### 2.1 Verify Kernel Memory Support
```bash
# Check if memory controller is now enabled
grep memory /proc/cgroups
# Expected: line with "memory" showing "1" in enabled column

# Compare with before state
diff /tmp/cgroups_before.txt /proc/cgroups
```

#### 2.2 Verify Docker Memory Support
```bash
# Check if Docker warnings are gone
docker info | grep -i warning
# Expected: NO output (warnings gone)

# Or full docker info to confirm
docker info
```

#### 2.3 Test Container Memory Limits
```bash
# Test basic memory limit functionality
docker run --memory=512m --rm alpine /bin/true
# Expected: container runs successfully

# Test with invalid memory limit (should fail gracefully)
docker run --memory=16g --rm alpine /bin/true 2>/dev/null
# Expected: Error about insufficient memory (shows limits working)
```

#### 2.4 Verify Available Memory
```bash
# Check system memory
free -h
# Expected: Similar to before but with memory limit support

# Check cgroup memory controllers
cat /proc/cgroups | grep memory
# Expected: "memory    X    Y    1" where 1 = enabled
```

### Phase 3: Crypto Trading Bot Testing (Agent Executes After Reboot)

#### 3.1 Start Updated Container
```bash
cd /home/pi/Projects/crypto-trader-bot
docker compose up -d
```

#### 3.2 Monitor Container Resource Usage
```bash
# Check container is using memory limits
docker stats crypto-trader-bot --no-stream
# Expected: Shows memory usage within 1.5G limit

# Detailed container info
docker inspect crypto-trader-bot | grep -A 10 "Memory"
```

#### 3.3 Verify Trading Bot Functionality
```bash
# Check API status
curl http://localhost:8000/api/status

# Check dashboard
curl http://localhost:8000/

# Check logs for memory-related messages
docker compose logs crypto-trader-bot | tail -10
```

---

## ROLLBACK PLAN (If Issues Occur)

### Immediate Rollback (Before Reboot)
```bash
sudo cp /boot/firmware/cmdline.txt.backup /boot/firmware/cmdline.txt
```

### Post-Reboot Rollback (If Issues After Reboot)
```bash
# Restore original cmdline.txt
sudo cp /boot/firmware/cmdline.txt.backup /boot/firmware/cmdline.txt

# Reboot to restore original configuration
sudo reboot
```

### Rollback Verification
```bash
# Verify memory controller is disabled again
grep memory /proc/cgroups
# Expected: No output (memory controller disabled)

# Verify Docker warnings return
docker info | grep -i warning
# Expected: "No memory limit support" warnings return
```

---

## EXPECTED OUTCOMES

### Before Implementation:
- ❌ Memory controller disabled
- ❌ Docker memory warnings
- ❌ No container memory isolation
- ❌ Multi-project risk: one container could consume all RAM

### After Implementation:
- ✅ Memory controller enabled
- ✅ Docker memory warnings gone
- ✅ Container memory limits working
- ✅ Trading bot protected from other projects
- ✅ Foundation for multi-project deployment
- ✅ Better system stability and resource management

### Memory Allocation Strategy (16GB Pi):
- **Trading Bot**: 512M-1.5G (conservative, mission-critical)
- **Future Projects**: 256M-512M each (typical web apps)
- **System Reserve**: 2G+ (always leave headroom)
- **Available for Others**: ~12G+ remaining

---

## TROUBLESHOOTING GUIDE

### If Reboot Firms:
1. **System doesn't boot**: Restore from cmdline.txt.backup using SD card recovery
2. **Docker doesn't start**: Check if cgroup settings caused systemd issues
3. **Container won't start**: Verify memory limits aren't too restrictive

### If Memory Controller Still Disabled:
1. **Check syntax errors** in cmdline.txt: `cat /boot/firmware/cmdline.txt`
2. **Verify kernel version**: `uname -a` (must support cgroup memory)
3. **Check dmesg for errors**: `dmesg | grep -i cgroup`

### If Docker Issues Persist:
1. **Restart Docker service**: `sudo systemctl restart docker`
2. **Check Docker logs**: `sudo journalctl -u docker.service`
3. **Verify container config**: `docker compose config`

---

## COMPLETION CHECKLIST

### Pre-Implementation:
- [ ] Backup cmdline.txt created
- [ ] Current system state documented
- [ ] docker-compose.yml updated with new limits
- [ ] User understands manual verification steps

### Post-Reboot Verification:
- [ ] Memory controller enabled (`grep memory /proc/cgroups`)
- [ ] Docker warnings gone (`docker info | grep -i warning`)
- [ ] Container memory limits working
- [ ] Trading bot operational
- [ ] No system performance degradation

### Final Validation:
- [ ] Crypto trading bot fully functional
- [ ] Memory limits active and working
- [ ] Multi-project foundation ready
- [ ] Documentation updated with final state

---

## FUTURE PROJECTIONS

### Benefits for Multi-Project Deployment:
1. **Resource Isolation**: Each project gets guaranteed memory allocation
2. **Stability**: One project can't crash others through memory consumption
3. **Planning**: Can allocate specific RAM per project type
4. **Monitoring**: Memory usage visible per container
5. **Production Ready**: Proper containerization for real applications

### Recommended Next Steps:
1. **Monitor Current Usage**: Run `docker stats` for a week to understand baseline
2. **Project Planning**: Document memory requirements for future projects
3. **Backup Strategy**: Regular cmdline.txt backups before system changes
4. **Monitoring Setup**: Consider adding memory alerting for containers

---

**Implementation Date:** To be executed
**Agent:** OpenCode Agent
**User:** Manual verification required after reboot
**Success Criteria:** Memory controller enabled, no Docker warnings, trading bot operational