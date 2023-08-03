# 2fauth

https://github.com/Bubka/2FAuth

2fauth app modified to work with postgresql instead of sqlite


Run the following query in postgresql first

```
CREATE COLLATION nocase (LOCALE = 'en_US.utf8');
```

First time setup:

```
php artisan passport:install
```

run this inside the totp container when initializing the db for the first time
